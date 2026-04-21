from flask import Blueprint, request, jsonify, session, current_app
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

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
