import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    collection: str = "2026-public-domain-day-film-contest"
    db_path: str = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "app.db"))
    session_secret: str = os.environ.get("SESSION_SECRET", "dev-secret-change-me")
    admin_token: str | None = os.environ.get("ADMIN_TOKEN")
    # "ia"    — delegate login to archive.org (default)
    # "local" — local email/password accounts
    auth_scheme: str = os.environ.get("AUTH_SCHEME", "ia")

def load_settings() -> Settings:
    return Settings()
