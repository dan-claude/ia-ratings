from flask import Blueprint, request, jsonify, session, current_app

auth_bp = Blueprint("auth", __name__)


def _auth_scheme() -> str:
    return current_app.settings.auth_scheme


@auth_bp.post("/api/auth/register")
def register():
    if _auth_scheme() == "ia":
        return jsonify({"error": "Registration is not supported in IA auth mode. Log in with your archive.org account."}), 400
    svc = current_app.services["auth"]
    data = request.get_json(silent=True) or {}
    try:
        uid = svc.register(data.get("email") or "", data.get("password") or "")
        session["user_id"] = uid
        return jsonify({"ok": True})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except KeyError as e:
        return jsonify({"error": str(e)}), 409


@auth_bp.post("/api/auth/login")
def login():
    svc = current_app.services["auth"]
    data = request.get_json(silent=True) or {}
    try:
        if _auth_scheme() == "ia":
            uid = svc.login_via_ia(data.get("username") or "", data.get("password") or "")
        else:
            uid = svc.login(data.get("email") or "", data.get("password") or "")
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
