from flask import Blueprint, current_app, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from ..auth_session import end_session, start_session

auth_bp = Blueprint("auth", __name__)

# M3: Rate limiter — init_app() is called in create_app() so it binds to the app.
# Routes that take a secret (the magic-link sign-in) put @limiter.limit(...) on themselves.
limiter = Limiter(key_func=get_remote_address)


@auth_bp.post("/api/auth/logout")
def logout():
    end_session()  # also deletes the server-side session, so a copied cookie stops working
    return jsonify({"ok": True})


@auth_bp.post("/api/auth/signin")
@limiter.limit("10 per minute; 50 per hour")
def signin():
    """Sign in with a magic link's secret (the client sends the token from the link's fragment
    after the person presses "Sign in"). The link is reusable until it expires or is cancelled."""
    data = request.get_json(silent=True) or {}
    uid = current_app.services["links"].redeem(data.get("token"))
    if uid is None:
        # One message for unknown, cancelled and expired links: don't tell a guesser which.
        return jsonify({"error": "This sign-in link is not valid any more. Ask an administrator for a new one."}), 401
    # L4: a fresh session after successful auth prevents session fixation.
    start_session(uid)
    return jsonify({"ok": True})
