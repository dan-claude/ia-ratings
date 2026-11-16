import hmac
import logging
import secrets

from flask import Blueprint, request, jsonify, session, current_app, redirect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from ..services.github_auth_service import GitHubAuthError

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)

# M3: Rate limiter — init_app() is called in create_app() so it binds to the app.
limiter = Limiter(key_func=get_remote_address)


def _auth_scheme() -> str:
    return current_app.settings.auth_scheme


@auth_bp.post("/api/auth/register")
@limiter.limit("10 per minute; 50 per hour")
def register():
    if _auth_scheme() == "ia":
        return jsonify({"error": "Registration is not supported in IA auth mode. Log in with your archive.org account."}), 400
    svc = current_app.services["auth"]
    data = request.get_json(silent=True) or {}
    try:
        uid = svc.register(data.get("email") or "", data.get("password") or "")
        # L4: Rotate session after successful auth to prevent session fixation.
        session.clear()
        session.permanent = True
        session["user_id"] = uid
        return jsonify({"ok": True})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except KeyError as e:
        return jsonify({"error": str(e)}), 409


@auth_bp.post("/api/auth/login")
@limiter.limit("10 per minute; 50 per hour")
def login():
    svc = current_app.services["auth"]
    data = request.get_json(silent=True) or {}
    try:
        if _auth_scheme() == "ia":
            uid = svc.login_via_ia(data.get("username") or "", data.get("password") or "")
        else:
            uid = svc.login(data.get("email") or "", data.get("password") or "")
        # L4: Rotate session after successful auth to prevent session fixation.
        session.clear()
        session.permanent = True
        session["user_id"] = uid
        return jsonify({"ok": True})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except PermissionError as e:
        return jsonify({"error": str(e)}), 401


@auth_bp.post("/api/auth/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# GitHub OAuth (browser redirects, not JSON). Only active when
# GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET are set.
# ---------------------------------------------------------------------------

def _github_service():
    return current_app.services.get("github_auth")


def _login_error(code: str):
    """Send the browser back to the SPA with a short error code (never free text)."""
    return redirect(f"/?auth_error={code}")


@auth_bp.get("/api/auth/github/login")
@limiter.limit("10 per minute; 50 per hour")
def github_login():
    svc = _github_service()
    if svc is None:
        return jsonify({"error": "GitHub login is not configured"}), 404
    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state
    return redirect(svc.authorize_url(state))


@auth_bp.get("/api/auth/github/callback")
@limiter.limit("10 per minute; 50 per hour")
def github_callback():
    svc = _github_service()
    if svc is None:
        return jsonify({"error": "GitHub login is not configured"}), 404

    # The state is single-use: pop it so a captured callback URL can't be replayed.
    expected = session.pop("oauth_state", None)
    given = request.args.get("state", "")
    if not expected or not hmac.compare_digest(str(expected), given):
        return _login_error("github_state")

    if request.args.get("error"):  # e.g. the user clicked "Cancel" on GitHub
        return _login_error("github_denied")

    try:
        uid = svc.login_with_code(request.args.get("code", ""))
    except GitHubAuthError:
        logger.warning("github.login.failed", exc_info=True)
        return _login_error("github_failed")

    # L4: Rotate session after successful auth to prevent session fixation.
    session.clear()
    session.permanent = True
    session["user_id"] = uid
    return redirect("/")
