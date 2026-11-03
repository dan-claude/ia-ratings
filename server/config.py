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
    collection: str = "2026-public-domain-day-film-contest"
    db_path: str = _env("DB_PATH", _DEFAULT_DB_PATH)
    session_secret: str = _env("SESSION_SECRET", _DEV_SECRET)
    # "ia"    — delegate login to archive.org (default)
    # "local" — local email/password accounts
    auth_scheme: str = _env("AUTH_SCHEME", "ia")


def load_settings() -> Settings:
    return Settings()
