import sqlite3
import requests as _requests
from werkzeug.security import generate_password_hash, check_password_hash
from ..models.user import User
from ..repositories.user_repo import UserRepository

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
        if not data.get("success"):
            reason = (data.get("values") or {}).get("reason") or "Invalid archive.org credentials"
            raise PermissionError(reason)
        row = self.users.get_by_ia_username(username)
        if row:
            return int(row["id"])
        return self.users.create_ia_user(username)

    def get_me(self, user_id: int) -> User:
        row = self.users.get_by_id(user_id)
        if not row:
            raise LookupError("User not found")
        return User(id=int(row["id"]), email=str(row["email"]), created_at=str(row["created_at"]), is_admin=("is_admin" in row.keys() and bool(row["is_admin"])), is_judge=("is_judge" in row.keys() and bool(row["is_judge"])))
