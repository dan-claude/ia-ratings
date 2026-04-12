import os
from flask import Blueprint, jsonify, current_app, Response, session, request

admin_bp = Blueprint("admin", __name__)

def _require_admin_user():
    uid = session.get("user_id")
    if not uid:
        return False, (jsonify({"error": "Not logged in"}), 401)
    users = current_app.repos["users"]
    row = users.get_by_id(int(uid))
    if not row:
        return False, (jsonify({"error": "Not logged in"}), 401)
    if not ("is_admin" in row.keys() and bool(row["is_admin"])):
        return False, (jsonify({"error": "Forbidden"}), 403)
    return True, None

@admin_bp.post("/api/admin/bootstrap")
def bootstrap_admin():
    """Temporary one-shot endpoint: promote a user to admin.
    Requires BOOTSTRAP_TOKEN env var to be set and passed as X-Bootstrap-Token header.
    Remove this endpoint after use.
    """
    token = os.environ.get("BOOTSTRAP_TOKEN")
    if not token:
        return jsonify({"error": "Bootstrap not enabled"}), 403
    if request.headers.get("X-Bootstrap-Token") != token:
        return jsonify({"error": "Forbidden"}), 403
    data = request.get_json(silent=True) or {}
    ia_username = data.get("ia_username", "").strip()
    email = data.get("email", "").strip()
    if not ia_username and not email:
        return jsonify({"error": "ia_username or email required"}), 400
    users = current_app.repos["users"]
    if ia_username:
        row = users.get_by_ia_username(ia_username)
        identifier = ia_username
    else:
        row = users.get_by_email(email)
        identifier = email
    if not row:
        return jsonify({"error": f"User not found: {identifier}"}), 404
    users.set_admin(int(row["id"]), True)
    return jsonify({"ok": True, "promoted": identifier})


@admin_bp.post("/api/admin/sync")
def sync():
    ok, err = _require_admin_user()
    if err:
        return err
    ia = current_app.services["ia"]
    films = current_app.repos["films"]
    added = ia.sync_collection(films)
    return jsonify({"ok": True, "added": added, "synced": added})

@admin_bp.get("/api/admin/ratings.csv")
def ratings_csv():
    ok, err = _require_admin_user()
    if err:
        return err
    ss = current_app.services["summary"]
    csv_text = ss.admin_ratings_csv()
    return Response(
        csv_text,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="ratings.csv"'},
    )
