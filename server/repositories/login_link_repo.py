import hashlib
import secrets
from typing import Optional

from ..db import Database


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class LoginLinkRepository:
    """Magic links. Only the SHA-256 of a link's secret is stored, so a link can be shown
    only at the moment it is created. Each user has at most one active (not revoked) link;
    an active link past its `expires_at` is simply expired until replaced or cancelled.
    Times are UTC strings in SQLite's `YYYY-MM-DD HH:MM:SS` format."""

    def __init__(self, db: Database):
        self.db = db

    def issue(self, user_id: int, expires_at: str) -> str:
        """Create a new link for the user, cancelling their previous one. Returns the secret."""
        token = secrets.token_urlsafe(32)
        conn = self.db.connect()
        try:
            with conn:
                conn.execute(
                    "UPDATE login_links SET revoked_at = datetime('now') WHERE user_id = ? AND revoked_at IS NULL",
                    (int(user_id),),
                )
                conn.execute(
                    "INSERT INTO login_links (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                    (_hash(token), int(user_id), expires_at),
                )
        finally:
            conn.close()
        return token

    def revoke(self, user_id: int) -> bool:
        """Cancel the user's active link. False if they had none."""
        conn = self.db.connect()
        try:
            with conn:
                cur = conn.execute(
                    "UPDATE login_links SET revoked_at = datetime('now') WHERE user_id = ? AND revoked_at IS NULL",
                    (int(user_id),),
                )
            return cur.rowcount > 0
        finally:
            conn.close()

    def set_expiry(self, user_id: int, expires_at: str) -> bool:
        """Change the expiry of the user's active link. False if they have none."""
        conn = self.db.connect()
        try:
            with conn:
                cur = conn.execute(
                    "UPDATE login_links SET expires_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                    (expires_at, int(user_id)),
                )
            return cur.rowcount > 0
        finally:
            conn.close()

    def find_valid_user_id(self, token: str) -> Optional[int]:
        """The user a link belongs to, if the link exists, is not cancelled and has not expired."""
        row = self.db.fetchone(
            "SELECT user_id FROM login_links WHERE token_hash = ? AND revoked_at IS NULL "
            "AND expires_at > datetime('now')",
            (_hash(token),),
        )
        return int(row["user_id"]) if row else None

    def active_links(self) -> dict[int, dict]:
        """user_id -> {"expires_at", "expired"} for every user with a non-cancelled link."""
        rows = self.db.fetchall(
            "SELECT user_id, expires_at, expires_at <= datetime('now') AS expired "
            "FROM login_links WHERE revoked_at IS NULL"
        )
        return {int(r["user_id"]): {"expires_at": r["expires_at"], "expired": bool(r["expired"])} for r in rows}
