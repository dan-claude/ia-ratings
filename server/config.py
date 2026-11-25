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


def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    db_path: str = _env("DB_PATH", _DEFAULT_DB_PATH)
    session_secret: str = _env("SESSION_SECRET", _DEV_SECRET)

    # Public address of the site (e.g. https://ratings.example.org), used by the command-line
    # tool to print magic links. The admin panel builds links from the address in the browser.
    public_url: str = _env("PUBLIC_URL", "")

    # How many reverse proxies sit in front of the app (Railway: 1). Only then is the
    # X-Forwarded-For header trusted, so the login rate limit sees each client's own
    # address instead of the proxy's. Leave 0 when clients connect directly: otherwise
    # anyone could spoof the header to dodge the limit.
    trusted_proxy_hops: int = field(default_factory=lambda: _env_int("TRUSTED_PROXY_HOPS", 0))


def load_settings() -> Settings:
    return Settings()
