"""Flask application entrypoint and dependency wiring.

This module uses an app-factory pattern (create_app()).

Run locally (from repo root):
    python -m server.app

Conveniences:
- Supports --host/--port/--debug/--no-debug
- If the requested port is busy, automatically falls back to the next available
  port (handy on macOS where 5000 is often occupied).
- Pass --with-client to run `npm install && npm run build` in client/ before
  starting the server; Flask will then serve the compiled app automatically.
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import os
import socket
import subprocess
import sys
import time
import uuid
from datetime import timedelta
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory, g
from werkzeug.exceptions import HTTPException

from server.config import load_settings, _DEV_SECRET
from server.db import Database
from server.logging_config import configure_logging

from server.repositories.criteria_repo import CriteriaRepository
from server.repositories.film_repo import FilmRepository
from server.repositories.rating_repo import RatingRepository
from server.repositories.user_repo import UserRepository

from server.services.auth_service import AuthService
from server.services.github_auth_service import GitHubAuthService
from server.services.ia_service import InternetArchiveService
from server.services.rating_service import RatingService
from server.services.summary_service import SummaryService

# Blueprints
from server.routes.admin import admin_bp
from server.routes.auth import auth_bp, limiter as auth_limiter
from server.routes.films import films_bp
from server.routes.user import user_bp

logger = logging.getLogger(__name__)


def create_app(settings: "Settings | None" = None) -> Flask:
    """Create and configure the Flask app.

    All configuration and dependency construction happens here (NOT at import time)
    so pytest and other importers behave predictably.

    Pass a Settings instance to override defaults (useful for tests and the CLI
    --auth-scheme flag).
    """

    configure_logging()
    if settings is None:
        settings = load_settings()

    # --- Serve the built React client (client/dist) directly from Flask ---
    repo_root = Path(__file__).resolve().parents[1]
    client_dist = repo_root / "client" / "dist"

    if client_dist.exists():
        app = Flask(__name__, static_folder=str(client_dist), static_url_path="/")
    else:
        app = Flask(__name__)

    # H2: Refuse to start in production with the default insecure secret.
    if settings.session_secret == _DEV_SECRET:
        import warnings
        warnings.warn(
            "SESSION_SECRET is not set — using the insecure development default. "
            "Set SESSION_SECRET to a random secret before deploying.",
            stacklevel=2,
        )

    app.secret_key = settings.session_secret
    app.config["DB_PATH"] = settings.db_path

    # M4 + M5: Secure session cookie settings.
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    # Only send the cookie over HTTPS in production (not on localhost dev).
    app.config["SESSION_COOKIE_SECURE"] = not (settings.session_secret == _DEV_SECRET)

    # --- Database + repos ---
    db = Database(settings.db_path)
    # Startup schema sanity check (helps debug local DB mismatches)
    try:
        cols = [r['name'] for r in db.fetchall('PRAGMA table_info(users)')]
        app.logger.info('Detected users columns: %s', cols)
        if 'is_admin' not in cols:
            app.logger.warning('users.is_admin column missing (migration should have added it)')
    except Exception:
        app.logger.exception('Failed to introspect users schema')
    users = UserRepository(db)
    films = FilmRepository(db, settings.collection)
    criteria = CriteriaRepository(db)
    ratings = RatingRepository(db)

    # --- Services ---
    ia = InternetArchiveService(settings.collection)
    auth = AuthService(users)
    github_auth = (
        GitHubAuthService(
            users,
            settings.github_client_id,
            settings.github_client_secret,
            settings.github_redirect_uri,
        )
        if settings.github_enabled
        else None
    )
    rating = RatingService(films, criteria, ratings)
    summary = SummaryService(criteria, films, ratings, settings.collection)

    # Expose for tests / routes
    app.settings = settings
    app.db = db
    app.repos = {
        "users": users,
        "films": films,
        "criteria": criteria,
        "ratings": ratings,
    }
    app.services = {
        "ia": ia,
        "auth": auth,
        "github_auth": github_auth,  # None unless GITHUB_CLIENT_ID/SECRET are set
        "rating": rating,
        "summary": summary,
    }

    # --- Request logging + request id ---
    @app.before_request
    def _before_request():
        g.request_id = uuid.uuid4().hex[:12]
        g.request_start = time.time()
        logger.debug(
            "request.start rid=%s method=%s path=%s",
            g.request_id,
            request.method,
            request.path,
        )

    @app.after_request
    def _after_request(response):
        dur_ms = (time.time() - getattr(g, "request_start", time.time())) * 1000.0
        rid = getattr(g, "request_id", "-")
        logger.info(
            "request.end rid=%s status=%s dur_ms=%.1f method=%s path=%s",
            rid,
            response.status_code,
            dur_ms,
            request.method,
            request.path,
        )
        response.headers["X-Request-Id"] = rid
        return response

    # --- Error handling ---
    @app.errorhandler(Exception)
    def _unhandled_error(err):
        # Preserve normal Flask/Werkzeug HTTP exceptions (404/405/etc.)
        if isinstance(err, HTTPException):
            return err

        rid = getattr(g, "request_id", "-")
        logger.exception("unhandled.error rid=%s", rid)
        return jsonify({"ok": False, "error": "Internal Server Error", "request_id": rid}), 500

    # M3: Initialise rate limiter (configured per-route in auth.py).
    # Uses in-memory storage by default; set RATELIMIT_STORAGE_URI=redis://...
    # in production if running multiple instances.
    app.config.setdefault("RATELIMIT_STORAGE_URI", "memory://")
    auth_limiter.init_app(app)

    # --- Register API blueprints ---
    # NOTE: Route modules already include full /api/... paths.
    app.register_blueprint(auth_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(films_bp)
    app.register_blueprint(admin_bp)

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True})

    # --- SPA routing (React build) ---
    @app.get("/")
    def index():
        if getattr(app, "static_folder", None) and Path(app.static_folder).exists():
            return send_from_directory(app.static_folder, "index.html")
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "Client not built",
                    "hint": "Run: cd client && npm install && npm run build (then restart the server).",
                }
            ),
            500,
        )

    @app.get("/<path:path>")
    def spa_fallback(path: str):
        if getattr(app, "static_folder", None) and Path(app.static_folder).exists():
            full = Path(app.static_folder) / path
            if full.exists() and full.is_file():
                return send_from_directory(app.static_folder, path)
            return send_from_directory(app.static_folder, "index.html")
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "Client not built",
                    "hint": "Run: cd client && npm install && npm run build (then restart the server).",
                }
            ),
            500,
        )

    return app


def _is_port_available(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
        return True
    except OSError:
        return False


def _pick_available_port(host: str, requested: int, max_tries: int = 100) -> int:
    if _is_port_available(host, requested):
        return requested
    for p in range(requested + 1, requested + 1 + max_tries):
        if _is_port_available(host, p):
            return p
    raise RuntimeError(f"No available port found in range {requested}-{requested + max_tries}")


def _build_client(repo_root: Path) -> None:
    """Run `npm install && npm run build` inside client/, streaming output."""
    client_dir = repo_root / "client"
    if not client_dir.exists():
        raise RuntimeError(f"client/ directory not found at {client_dir}")
    print(f"Building client in {client_dir} …")
    for cmd in (["npm", "install"], ["npm", "run", "build"]):
        result = subprocess.run(cmd, cwd=client_dir)
        if result.returncode != 0:
            raise SystemExit(f"Command {cmd} failed with exit code {result.returncode}")
    print("Client build complete.")


def main(argv: list[str] | None = None) -> int:
    env_host = os.getenv("FLASK_RUN_HOST", "0.0.0.0")
    env_port = int(os.getenv("FLASK_RUN_PORT", "5000"))
    env_debug = os.getenv("FLASK_DEBUG", "0")

    parser = argparse.ArgumentParser(description="Run the IA Ratings Flask server")
    parser.add_argument("--host", default=env_host, help="Bind host (default: %(default)s)")
    parser.add_argument("--port", type=int, default=env_port, help="Bind port (default: %(default)s)")
    parser.add_argument(
        "--with-client",
        action="store_true",
        help="Run `npm install && npm run build` in client/ before starting the server",
    )
    parser.add_argument(
        "--auth-scheme",
        choices=["ia", "local"],
        default=None,
        help=(
            "Authentication scheme: 'ia' delegates login to archive.org (default); "
            "'local' uses local email/password accounts. "
            "Overrides the AUTH_SCHEME env var."
        ),
    )
    dbg = parser.add_mutually_exclusive_group()
    dbg.add_argument("--debug", action="store_true", help="Enable debug mode")
    dbg.add_argument("--no-debug", action="store_true", help="Disable debug mode")
    args = parser.parse_args(argv)

    if args.no_debug:
        debug = False
    elif args.debug:
        debug = True
    else:
        debug = env_debug == "1"

    host = args.host
    port = args.port

    chosen_port = _pick_available_port(host, port)
    if chosen_port != port:
        print(f"Port {port} is busy; falling back to {chosen_port}.")

    if args.with_client:
        repo_root = Path(__file__).resolve().parents[1]
        _build_client(repo_root)

    settings = load_settings()
    if args.auth_scheme is not None:
        settings = dataclasses.replace(settings, auth_scheme=args.auth_scheme)
    print(f"Auth scheme: {settings.auth_scheme}")

    app = create_app(settings=settings)
    app.run(host=host, port=chosen_port, debug=debug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
