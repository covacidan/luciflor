import os
from dataclasses import dataclass


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str
    app_public_url: str
    keycloak_public_url: str
    keycloak_internal_url: str
    keycloak_realm: str
    keycloak_client_id: str
    keycloak_client_secret: str
    session_secret: str
    session_https_only: bool

    @property
    def realm_public(self) -> str:
        """Realm base URL as the browser (and the token issuer) sees it."""
        return f"{self.keycloak_public_url.rstrip('/')}/realms/{self.keycloak_realm}"

    @property
    def realm_internal(self) -> str:
        """Realm base URL for server-to-server calls inside the Docker network."""
        return f"{self.keycloak_internal_url.rstrip('/')}/realms/{self.keycloak_realm}"

    @property
    def admin_api(self) -> str:
        return f"{self.keycloak_internal_url.rstrip('/')}/admin/realms/{self.keycloak_realm}"

    @property
    def redirect_uri(self) -> str:
        return f"{self.app_public_url.rstrip('/')}/auth/callback"


def load_settings() -> Settings:
    return Settings(
        database_url=os.environ["DATABASE_URL"],
        app_public_url=os.environ.get("APP_PUBLIC_URL", "http://localhost:8211"),
        keycloak_public_url=os.environ.get("KEYCLOAK_PUBLIC_URL", "http://localhost:8210"),
        keycloak_internal_url=os.environ.get(
            "KEYCLOAK_INTERNAL_URL", os.environ.get("KEYCLOAK_PUBLIC_URL", "http://localhost:8210")
        ),
        keycloak_realm=os.environ.get("KEYCLOAK_REALM", "luciflor"),
        keycloak_client_id=os.environ.get("KEYCLOAK_CLIENT_ID", "luciflor-web"),
        keycloak_client_secret=os.environ["KEYCLOAK_CLIENT_SECRET"],
        session_secret=os.environ["SESSION_SECRET"],
        session_https_only=_bool(os.environ.get("SESSION_HTTPS_ONLY")),
    )


settings = load_settings()
