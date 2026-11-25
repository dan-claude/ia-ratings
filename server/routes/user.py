from flask import Blueprint, Response, jsonify, current_app

from ..auth_session import current_user_id
from ..models.user import User

user_bp = Blueprint("user", __name__)

def _require_auth():
    uid = current_user_id()
    if not uid:
        return None, (jsonify({"error": "Not logged in"}), 401)
    return uid, None


@user_bp.get("/api/me")
def me():
    uid, err = _require_auth()
    if err:
        return err
    row = current_app.repos["users"].get_by_id(uid)
    if not row:
        return jsonify({"error": "Not logged in"}), 401
    user = User(
        id=int(row["id"]), email=str(row["email"]), created_at=str(row["created_at"]),
        is_admin=bool(row["is_admin"]), is_reviewer=bool(row["is_reviewer"]), is_judge=bool(row["is_judge"]),
    )
    return jsonify({
        "id": user.id, "email": user.email, "created_at": user.created_at,
        "is_admin": user.is_admin, "is_reviewer": user.is_reviewer, "is_judge": user.is_judge,
        "roles": user.roles,
    })


def _require_judge():
    uid, err = _require_auth()
    if err:
        return None, err
    if not current_app.services["rating"].is_judge(uid):
        return None, (jsonify({"error": "Forbidden"}), 403)
    return uid, None


@user_bp.get("/api/me/results")
def my_results():
    """A judge's own ranked list of the pool films they have rated, with their scores and comments."""
    uid, err = _require_judge()
    if err:
        return err
    return jsonify(current_app.services["rating"].judge_results(uid))


@user_bp.get("/api/me/results.csv")
def my_results_csv():
    """The same list as a CSV download (judges only)."""
    uid, err = _require_judge()
    if err:
        return err
    return Response(
        current_app.services["rating"].judge_results_csv(uid),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="my_ratings.csv"'},
    )


@user_bp.get("/api/categories")
def categories():
    uid, err = _require_auth()
    if err:
        return err
    return jsonify(current_app.services["rating"].list_categories())
