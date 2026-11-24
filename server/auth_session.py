"""Login sessions: a signed cookie plus a matching server-side record.

The cookie holds `user_id` and a random `sid`. A request counts as logged in only if
the server still has that session (so logout really ends it, and sessions can be
revoked in bulk, e.g. when a backup restore replaces the users table). Roles are
looked up from the database on every request, never stored in the cookie.
"""
from typing import Optional

from flask import current_app, session


def start_session(user_id: int) -> None:
    """Begin a fresh login for `user_id`, discarding whatever session came with the request."""
    old_sid = session.get("sid")
    if old_sid:
        current_app.repos["sessions"].delete(old_sid)  # no session fixation, no orphan row
    session.clear()
    session.permanent = True
    session["user_id"] = int(user_id)
    session["sid"] = current_app.repos["sessions"].create(int(user_id))


def end_session() -> None:
    sid = session.get("sid")
    if sid:
        current_app.repos["sessions"].delete(sid)
    session.clear()


def current_user_id() -> Optional[int]:
    """The logged-in user's id, or None when there is no valid session."""
    uid = session.get("user_id")
    sid = session.get("sid")
    if not uid or not isinstance(sid, str):
        return None
    try:
        uid = int(uid)
    except (TypeError, ValueError):
        return None
    if not current_app.repos["sessions"].is_valid(sid, uid):
        return None
    return uid
