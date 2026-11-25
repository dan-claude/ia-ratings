import hashlib
import secrets
from typing import Optional

from ..db import Database

# Must match Flask's PERMANENT_SESSION_LIFETIME (set in app.py).
SESSION_LIFETIME_HOURS = 8


def _hash(sid: str) -> str:
    return hashlib.sha256(sid.encode("utf-8")).hexdigest()


class SessionRepository:
    """Server-side record of live logins; the cookie alone is not enough to be logged in."""

    def __init__(self, db: Database):
        self.db = db

    def create(self, user_id: int, sid: Optional[str] = None) -> str:
        """Start a session for `user_id` and return its random id (put it in the cookie).

        Pass `sid` only to re-register an existing session (e.g. after a restore).
        """
        sid = sid or secrets.token_urlsafe(32)
        conn = self.db.connect()
        try:
            with conn:
                conn.execute(
                    "DELETE FROM user_sessions WHERE created_at <= datetime('now', ?)",
                    (f"-{SESSION_LIFETIME_HOURS} hours",),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO user_sessions (sid_hash, user_id) VALUES (?, ?)",
                    (_hash(sid), int(user_id)),
                )
        finally:
            conn.close()
        return sid

    def is_valid(self, sid: str, user_id: int) -> bool:
        row = self.db.fetchone(
            "SELECT 1 FROM user_sessions WHERE sid_hash = ? AND user_id = ? "
            "AND created_at > datetime('now', ?)",
            (_hash(sid), int(user_id), f"-{SESSION_LIFETIME_HOURS} hours"),
        )
        return row is not None

    def delete(self, sid: str) -> None:
        conn = self.db.connect()
        try:
            with conn:
                conn.execute("DELETE FROM user_sessions WHERE sid_hash = ?", (_hash(sid),))
        finally:
            conn.close()

    def delete_for_user(self, user_id: int, keep_sid: Optional[str] = None) -> None:
        """End all of a person's logins (optionally keeping one, e.g. the admin's own)."""
        conn = self.db.connect()
        try:
            with conn:
                if keep_sid:
                    conn.execute(
                        "DELETE FROM user_sessions WHERE user_id = ? AND sid_hash != ?",
                        (int(user_id), _hash(keep_sid)),
                    )
                else:
                    conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (int(user_id),))
        finally:
            conn.close()

    def delete_all(self) -> None:
        conn = self.db.connect()
        try:
            with conn:
                conn.execute("DELETE FROM user_sessions")
        finally:
            conn.close()
