import os
from dataclasses import dataclass, field

_DEV_SECRET = "dev-secret-change-me"
_DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "app.db")


def _env(name: str, default: str):
    """Field default that reads the env var each time Settings() is created.

    (A plain `= os.environ.get(...)` default is evaluated once, at import time,
    so later env changes such as per-test DB_PATH values would be ignored.)
    """
    return field(default_factory=lambda: os.environ.get(name, default))


@dataclass(frozen=True)
class Settings:
    # DEFAULT Internet Archive collection, used until an admin sets one in the admin
    # panel (stored in the database: app_settings 'collection'). Films are only shown
    # to raters (and synced / imported) for the active collection.
    collection: str = "2026-public-domain-day-film-contest"
    db_path: str = _env("DB_PATH", _DEFAULT_DB_PATH)
    session_secret: str = _env("SESSION_SECRET", _DEV_SECRET)
    # "ia"    — delegate login to archive.org (default)
    # "local" — local email/password accounts
    auth_scheme: str = _env("AUTH_SCHEME", "ia")
    # Optional "Continue with GitHub" login, offered alongside the scheme above.
    # Enabled only when both the client id and secret are set.
    github_client_id: str = _env("GITHUB_CLIENT_ID", "")
    github_client_secret: str = _env("GITHUB_CLIENT_SECRET", "")
    # Normally leave empty: GitHub then uses the callback URL registered on the
    # OAuth app. Set it only if you registered more than one callback URL.
    github_redirect_uri: str = _env("GITHUB_REDIRECT_URI", "")

    @property
    def github_enabled(self) -> bool:
        return bool(self.github_client_id and self.github_client_secret)

    @property
    def oauth_providers(self) -> list[str]:
        """Names of the OAuth providers the login screen should offer."""
        return ["github"] if self.github_enabled else []


def load_settings() -> Settings:
    return Settings()
