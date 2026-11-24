from flask import Blueprint, jsonify, current_app, request

from ..auth_session import current_user_id

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
    rs = current_app.services["rating"]
    film = rs.get_next_unrated_film(uid)
    if not film:
        # Distinguish "nothing has been loaded" from "this user rated everything".
        if rs.count_films() == 0:
            return jsonify({
                "error": "The film database hasn't been set up yet. An admin needs to sync it from the Internet Archive.",
                "code": "no_films",
            }), 404
        return jsonify({
            "error": "You've rated every film — there's nothing left to rate.",
            "code": "all_rated",
        }), 404
    return jsonify({
        "identifier": film["identifier"],
        "title": film["title"],
        "description": film.get("description"),
        "embedUrl": f"https://archive.org/embed/{film['identifier']}",
    })

@films_bp.get("/api/films/<identifier>")
def film(identifier: str):
    uid, err = _require_auth()
    if err:
        return err
    rs = current_app.services["rating"]
    film = rs.get_film_by_identifier(identifier)
    if not film:
        return jsonify({"error": "Film not found"}), 404
    return jsonify({
        "identifier": film["identifier"],
        "title": film["title"],
        "description": film.get("description"),
        "embedUrl": f"https://archive.org/embed/{film['identifier']}",
    })

@films_bp.post("/api/films/<identifier>/ratings")
def rate(identifier: str):
    uid, err = _require_auth()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    scores = data.get("scores")
    rs = current_app.services["rating"]
    try:
        rs.submit_rating(uid, identifier, scores)
        return jsonify({"ok": True})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except LookupError as e:
        return jsonify({"error": str(e)}), 404


def _require_judge():
    """(user_id, None) for a logged-in judge; otherwise (None, error response)."""
    uid, err = _require_auth()
    if err:
        return None, err
    row = current_app.repos["users"].get_by_id(uid)
    if not row:
        return None, (jsonify({"error": "Not logged in"}), 401)
    if "judge" not in current_app.repos["users"].roles_of(row):
        return None, (jsonify({"error": "Forbidden"}), 403)
    return uid, None

@films_bp.get("/api/films/<identifier>/notes")
def list_notes(identifier: str):
    uid, err = _require_judge()
    if err:
        return err
    try:
        return jsonify(current_app.services["notes"].list_notes(identifier))
    except LookupError as e:
        return jsonify({"error": str(e)}), 404

@films_bp.post("/api/films/<identifier>/notes")
def add_note(identifier: str):
    uid, err = _require_judge()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        note = current_app.services["notes"].add_note(uid, identifier, data.get("text"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except LookupError as e:
        return jsonify({"error": str(e)}), 404
    return jsonify(note), 201
