from flask import Blueprint, jsonify, session, current_app

user_bp = Blueprint("user", __name__)

def _require_auth():
    uid = session.get("user_id")
    if not uid:
        return None, (jsonify({"error": "Not logged in"}), 401)
    return int(uid), None

@user_bp.get("/api/config")
def config():
    return jsonify({
        "auth_scheme": current_app.settings.auth_scheme,
        "oauth_providers": current_app.settings.oauth_providers,
    })


@user_bp.get("/api/me")
def me():
    uid, err = _require_auth()
    if err:
        return err
    svc = current_app.services["auth"]
    try:
        me = svc.get_me(uid)
        return jsonify({"id": me.id, "email": me.email, "created_at": me.created_at, "is_admin": me.is_admin})
    except LookupError:
        return jsonify({"error": "Not logged in"}), 401

@user_bp.get("/api/criteria")
def criteria():
    uid, err = _require_auth()
    if err:
        return err
    rs = current_app.services["rating"]
    rows = rs.list_active_criteria()
    return jsonify([{
        "key": r["key"],
        "label": r["label"],
        "min": r["min_score"],
        "max": r["max_score"],
        "sortOrder": r["sort_order"],
        "active": r["active"],
    } for r in rows])
