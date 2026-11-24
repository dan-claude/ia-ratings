import logging
import sqlite3

import requests as _requests
from werkzeug.security import generate_password_hash, check_password_hash
from ..models.user import User
from ..repositories.user_repo import UserRepository

logger = logging.getLogger(__name__)


def _canonical_ia_name(values: dict, typed: str) -> str:
    """The stable, lower-case archive.org account name for a successful login.

    archive.org accepts several things in the login box (username in any case, email
    address), so the typed text must not become the account key: one person would get
    several accounts. Use the name archive.org itself reports for the account.
    """
    for key in ("itemname", "screenname"):
        value = values.get(key)
        if isinstance(value, str):
            value = value.strip().lstrip("@").strip().lower()
            if value:
                return value
    if "@" in typed:
        # No name in the response and an email was typed: can't tell which account this is.
        raise PermissionError("Please log in with your archive.org username rather than your email address.")
    return typed.lower()


class AuthService:
    def __init__(self, users: UserRepository):
        self.users = users

    def register(self, email: str, password: str) -> int:
        email = email.strip().lower()
        if not email or not password:
            raise ValueError("email and password required")
        ph = generate_password_hash(password)
        try:
            return self.users.create_user(email, ph)
        except sqlite3.IntegrityError as e:
            raise KeyError("Email already registered") from e

    def login(self, email: str, password: str) -> int:
        email = email.strip().lower()
        if not email or not password:
            raise ValueError("email and password required")
        row = self.users.get_by_email(email)
        if not row or not check_password_hash(row["password_hash"], password):
            raise PermissionError("Invalid credentials")
        return int(row["id"])

    def login_via_ia(self, username: str, password: str) -> int:
        username = username.strip()
        if not username or not password:
            raise ValueError("username and password required")
        try:
            resp = _requests.post(
                "https://archive.org/services/xauthn/?op=login",
                json={"email": username, "password": password},
                timeout=10,
            )
            data = resp.json()
        except _requests.exceptions.RequestException as exc:
            raise PermissionError("Could not reach archive.org") from exc
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        if not data.get("success"):
            reason = (data.get("values") or {}).get("reason") or "Invalid archive.org credentials"
            raise PermissionError(reason)
        values = data.get("values") if isinstance(data.get("values"), dict) else {}
        # Key names only: the values include session cookies and API keys.
        logger.info("ia.login.response keys=%s", sorted(values.keys()))
        name = _canonical_ia_name(values, username)

        row = self.users.get_by_ia_username(name)
        if not row and "@" in username:
            # Older accounts were keyed on whatever was typed, possibly an email address:
            # adopt that account (it can only match if this person proved they own it).
            legacy = self.users.get_by_ia_username(username)
            if legacy:
                try:
                    self.users.set_ia_username(int(legacy["id"]), name)
                except sqlite3.IntegrityError:
                    pass
                row = legacy
        if row:
            return int(row["id"])
        try:
            return self.users.create_ia_user(name)
        except sqlite3.IntegrityError:
            # A concurrent login for the same account created it first.
            row = self.users.get_by_ia_username(name)
            if row:
                return int(row["id"])
            raise

    def get_me(self, user_id: int) -> User:
        row = self.users.get_by_id(user_id)
        if not row:
            raise LookupError("User not found")
        return User(id=int(row["id"]), email=str(row["email"]), created_at=str(row["created_at"]), is_admin=("is_admin" in row.keys() and bool(row["is_admin"])), is_judge=("is_judge" in row.keys() and bool(row["is_judge"])))
