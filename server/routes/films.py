from flask import Blueprint, jsonify, current_app, request

from ..auth_session import current_user_id
from ..repositories.rating_repo import AlreadyRated
from ..services.rating_service import NothingToRate

films_bp = Blueprint("films", __name__)

def _require_auth():
    uid = current_user_id()
    if not uid:
        return None, (jsonify({"error": "Not logged in"}), 401)
    return uid, None

@films_bp.get("/api/films/next")
def next_film():
    uid, err = _require_auth()
    if err:
        return err
    try:
        return jsonify(current_app.services["rating"].get_next_film(uid))
    except NothingToRate as e:
        # Not an error as such: the person has no films, or has finished them all.
        return jsonify({"error": str(e), "code": e.code}), 404

@films_bp.get("/api/films/<identifier>")
def film(identifier: str):
    uid, err = _require_auth()
    if err:
        return err
    film = current_app.services["rating"].get_film(uid, identifier)
    if not film:
        return jsonify({"error": "Film not found"}), 404
    return jsonify(film)

@films_bp.post("/api/films/<identifier>/ratings")
def rate(identifier: str):
    uid, err = _require_auth()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        total = current_app.services["rating"].submit_rating(uid, identifier, data.get("scores"), data.get("comment"))
        return jsonify({"ok": True, "total": total})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except LookupError as e:
        return jsonify({"error": str(e)}), 404
    except AlreadyRated:
        return jsonify({"error": "You have already submitted this film. Ratings can't be changed."}), 409
