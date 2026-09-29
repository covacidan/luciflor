"""OIDC login against Keycloak (authorization code + PKCE) and access guards."""

import base64
import hashlib
import secrets
import time
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import HTTPException, Request

from .config import settings


class LoginRequired(Exception):
    """Raised by guards; turned into a redirect to /login by an exception handler."""


_jwks_client: jwt.PyJWKClient | None = None


def _jwks() -> jwt.PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(
            f"{settings.realm_internal}/protocol/openid-connect/certs", cache_keys=True
        )
    return _jwks_client


def build_login_url(request: Request, next_url: str = "/") -> str:
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    request.session["oidc"] = {"state": state, "verifier": verifier, "next": _safe_next(next_url)}
    params = {
        "client_id": settings.keycloak_client_id,
        "response_type": "code",
        "scope": "openid profile",
        "redirect_uri": settings.redirect_uri,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{settings.realm_public}/protocol/openid-connect/auth?{urlencode(params)}"


def _safe_next(url: str) -> str:
    # Only allow local paths to avoid open redirects.
    return url if url.startswith("/") and not url.startswith("//") else "/"


def complete_login(request: Request, code: str, state: str) -> str:
    pending = request.session.pop("oidc", None)
    if not pending or not secrets.compare_digest(pending["state"], state):
        raise HTTPException(400, "Sesiune de autentificare invalidă. Încercați din nou.")

    resp = httpx.post(
        f"{settings.realm_internal}/protocol/openid-connect/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.redirect_uri,
            "client_id": settings.keycloak_client_id,
            "client_secret": settings.keycloak_client_secret,
            "code_verifier": pending["verifier"],
        },
        timeout=10,
    )
    if resp.status_code != 200:
        raise HTTPException(400, "Autentificarea a eșuat.")
    tokens = resp.json()

    id_claims = _verify(tokens["id_token"], audience=settings.keycloak_client_id)
    access_claims = _verify(tokens["access_token"], audience=None)

    roles = access_claims.get("realm_access", {}).get("roles", [])
    request.session["user"] = {
        "sub": id_claims["sub"],
        "username": id_claims.get("preferred_username", ""),
        "name": id_claims.get("name") or id_claims.get("preferred_username", ""),
        "is_admin": "admin" in roles,
        "exp": int(time.time()) + 12 * 3600,
    }
    request.session["id_token"] = tokens["id_token"]
    return pending["next"]


def _verify(token: str, audience: str | None) -> dict:
    key = _jwks().get_signing_key_from_jwt(token).key
    return jwt.decode(
        token,
        key,
        algorithms=["RS256"],
        audience=audience,
        issuer=settings.realm_public,
        options={"verify_aud": audience is not None},
        leeway=30,
    )


def logout_url(request: Request) -> str:
    id_token = request.session.get("id_token")
    request.session.clear()
    params = {"post_logout_redirect_uri": f"{settings.app_public_url.rstrip('/')}/"}
    if id_token:
        params["id_token_hint"] = id_token
    else:
        params["client_id"] = settings.keycloak_client_id
    return f"{settings.realm_public}/protocol/openid-connect/logout?{urlencode(params)}"


def current_user(request: Request) -> dict | None:
    user = request.session.get("user")
    if user and user.get("exp", 0) > time.time():
        return user
    return None


def require_user(request: Request) -> dict:
    user = current_user(request)
    if not user:
        raise LoginRequired()
    return user


def require_admin(request: Request) -> dict:
    user = require_user(request)
    if not user.get("is_admin"):
        raise HTTPException(403, "Nu aveți drepturi de administrator.")
    return user
