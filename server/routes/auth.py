from flask import Blueprint, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from ..auth_session import end_session

auth_bp = Blueprint("auth", __name__)

# M3: Rate limiter — init_app() is called in create_app() so it binds to the app.
# Routes that take a secret (the magic-link sign-in) put @limiter.limit(...) on themselves.
limiter = Limiter(key_func=get_remote_address)


@auth_bp.post("/api/auth/logout")
def logout():
    end_session()  # also deletes the server-side session, so a copied cookie stops working
    return jsonify({"ok": True})
