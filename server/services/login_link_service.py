import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..repositories.login_link_repo import LoginLinkRepository
from ..repositories.session_repo import SessionRepository
from ..repositories.user_repo import UserRepository, normalize_email

DEFAULT_LINK_DAYS = 30
_DB_FORMAT = "%Y-%m-%d %H:%M:%S"
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def parse_expiry(value, now: Optional[datetime] = None) -> str:
    """Turn what the admin chose into a UTC `YYYY-MM-DD HH:MM:SS` string (must be in the future).

    None -> DEFAULT_LINK_DAYS from now. "YYYY-MM-DD" -> the end of that day (UTC).
    A full ISO-8601 date-time is converted to UTC (no zone = UTC).
    """
    now = now or datetime.now(timezone.utc)
    if value is None or value == "":
        dt = now + timedelta(days=DEFAULT_LINK_DAYS)
    elif isinstance(value, str):
        v = value.strip()
        try:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
                dt = datetime.strptime(v, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
            else:
                dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
                dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
        except ValueError:
            raise ValueError("expires_at must be a date (YYYY-MM-DD) or an ISO-8601 date-time") from None
    else:
        raise ValueError("expires_at must be a date (YYYY-MM-DD) or an ISO-8601 date-time")
    if dt <= now:
        raise ValueError("The expiry must be in the future")
    return dt.strftime(_DB_FORMAT)


def to_iso(db_time: str) -> str:
    """`YYYY-MM-DD HH:MM:SS` (UTC) -> `YYYY-MM-DDTHH:MM:SSZ`."""
    return db_time.replace(" ", "T") + "Z"


class LoginLinkService:
    """Invite people and manage their magic links.

    The app never sends email: the admin gets the link back once and passes it on.
    Issuing a new link, or cancelling one, also ends that person's current logins
    (so a forwarded or stolen link stops working everywhere).
    """

    def __init__(self, users: UserRepository, links: LoginLinkRepository, sessions: SessionRepository):
        self.users = users
        self.links = links
        self.sessions = sessions

    @staticmethod
    def link_payload(token: str, expires_at: str) -> dict:
        # The secret goes in the URL fragment: browsers never send it to the server, so it
        # stays out of server logs and Referer headers. The admin panel adds the origin.
        return {"token": token, "path": f"/signin#{token}", "expires_at": to_iso(expires_at)}

    def invite(self, email: str, roles: list[str], expires_at=None) -> dict:
        """Create a user with `roles` and their first link. ValueError: bad input; KeyError: email taken."""
        email = normalize_email(email)
        if len(email) > 254 or not _EMAIL_RE.match(email):
            raise ValueError("Enter a valid email address")
        expiry = parse_expiry(expires_at)  # validate before creating anything
        try:
            uid = self.users.create_user(email, roles)
        except sqlite3.IntegrityError:
            raise KeyError("That email address already has an account") from None
        token = self.links.issue(uid, expiry)
        return {"user_id": uid, "email": email, "roles": list(roles), "link": self.link_payload(token, expiry)}

    def reissue(self, user_id: int, expires_at=None, keep_sid: Optional[str] = None) -> dict:
        """A new link for an existing user; the old one stops working and their logins end."""
        if not self.users.get_by_id(user_id):
            raise LookupError("User not found")
        expiry = parse_expiry(expires_at)
        token = self.links.issue(user_id, expiry)
        self.sessions.delete_for_user(user_id, keep_sid)
        return self.link_payload(token, expiry)

    def cancel(self, user_id: int, keep_sid: Optional[str] = None) -> bool:
        if not self.users.get_by_id(user_id):
            raise LookupError("User not found")
        had = self.links.revoke(user_id)
        self.sessions.delete_for_user(user_id, keep_sid)
        return had

    def change_expiry(self, user_id: int, expires_at) -> str:
        """Move the expiry of the user's active link (a lapsed one can be revived this way)."""
        if not self.users.get_by_id(user_id):
            raise LookupError("User not found")
        if expires_at is None or expires_at == "":
            raise ValueError("expires_at is required")
        expiry = parse_expiry(expires_at)
        if not self.links.set_expiry(user_id, expiry):
            raise LookupError("This person has no active link; create a new one")
        return to_iso(expiry)

    def redeem(self, token) -> Optional[int]:
        """The user id for a valid link, else None. Every use is checked against the expiry."""
        if not isinstance(token, str) or not token or len(token) > 200:
            return None
        return self.links.find_valid_user_id(token)

    def list_users(self) -> list[dict]:
        links = self.links.active_links()
        out = []
        for row in self.users.list_all():
            link = links.get(int(row["id"]))
            out.append({
                "id": int(row["id"]),
                "email": row["email"],
                "created_at": row["created_at"],
                "is_admin": bool(row["is_admin"]),
                "is_reviewer": bool(row["is_reviewer"]),
                "is_judge": bool(row["is_judge"]),
                "roles": UserRepository.roles_of(row),
                "link": None if not link else {
                    "state": "expired" if link["expired"] else "active",
                    "expires_at": to_iso(link["expires_at"]),
                },
            })
        return out
