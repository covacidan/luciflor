"""Website user management through the Keycloak Admin REST API.

The web client's service account holds realm-management/manage-users, so the
app can create, update and delete users in the "luciflor" realm.
"""

import time

import httpx

from .config import settings


class KeycloakError(Exception):
    pass


_token: dict = {"value": None, "exp": 0.0}


def _admin_token() -> str:
    if _token["value"] and _token["exp"] - 30 > time.time():
        return _token["value"]
    resp = httpx.post(
        f"{settings.realm_internal}/protocol/openid-connect/token",
        data={
            "grant_type": "client_credentials",
            "client_id": settings.keycloak_client_id,
            "client_secret": settings.keycloak_client_secret,
        },
        timeout=10,
    )
    if resp.status_code != 200:
        raise KeycloakError("Nu mă pot conecta la Keycloak.")
    data = resp.json()
    _token["value"] = data["access_token"]
    _token["exp"] = time.time() + data.get("expires_in", 60)
    return _token["value"]


def _request(method: str, path: str, **kwargs) -> httpx.Response:
    headers = {"Authorization": f"Bearer {_admin_token()}"}
    resp = httpx.request(method, f"{settings.admin_api}{path}", headers=headers, timeout=10, **kwargs)
    if resp.status_code >= 400:
        detail = ""
        try:
            body = resp.json()
            detail = body.get("errorMessage") or body.get("error_description") or body.get("error") or ""
        except ValueError:
            pass
        if resp.status_code == 409:
            raise KeycloakError("Există deja un utilizator cu acest nume.")
        raise KeycloakError(f"Eroare Keycloak ({resp.status_code}) {detail}".strip())
    return resp


def _admin_role() -> dict:
    return _request("GET", "/roles/admin").json()


def _is_service_account(user: dict) -> bool:
    return user.get("username", "").startswith("service-account-")


def list_users() -> list[dict]:
    users = [u for u in _request("GET", "/users", params={"max": 500}).json() if not _is_service_account(u)]
    admin_ids = {u["id"] for u in _request("GET", "/roles/admin/users", params={"max": 500}).json()}
    for u in users:
        u["is_admin"] = u["id"] in admin_ids
        u["display_name"] = " ".join(p for p in (u.get("firstName"), u.get("lastName")) if p)
    return sorted(users, key=lambda u: u["username"])


def get_user(user_id: str) -> dict:
    user = _request("GET", f"/users/{user_id}").json()
    if _is_service_account(user):
        raise KeycloakError("Utilizator inexistent.")
    roles = _request("GET", f"/users/{user_id}/role-mappings/realm").json()
    user["is_admin"] = any(r["name"] == "admin" for r in roles)
    return user


def create_user(username: str, full_name: str, password: str, is_admin: bool) -> None:
    resp = _request(
        "POST",
        "/users",
        json={
            "username": username,
            "firstName": full_name or None,
            "enabled": True,
            "credentials": [{"type": "password", "value": password, "temporary": False}],
        },
    )
    user_id = resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1]
    if is_admin:
        _request("POST", f"/users/{user_id}/role-mappings/realm", json=[_admin_role()])


def update_user(user_id: str, full_name: str, enabled: bool, password: str | None, is_admin: bool) -> None:
    current = get_user(user_id)
    _request(
        "PUT",
        f"/users/{user_id}",
        json={"firstName": full_name, "lastName": current.get("lastName"), "enabled": enabled},
    )
    if password:
        _request(
            "PUT",
            f"/users/{user_id}/reset-password",
            json={"type": "password", "value": password, "temporary": False},
        )
    if is_admin != current["is_admin"]:
        method = "POST" if is_admin else "DELETE"
        _request(method, f"/users/{user_id}/role-mappings/realm", json=[_admin_role()])


def delete_user(user_id: str) -> None:
    get_user(user_id)  # refuses service accounts
    _request("DELETE", f"/users/{user_id}")
