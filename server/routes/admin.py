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
