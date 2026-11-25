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
import secrets
import socket
import subprocess
import sys
import time
import uuid
from datetime import timedelta
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory, g
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from server.config import load_settings, _DEV_SECRET
from server.db import Database, LegacyDatabaseError
from server.logging_config import configure_logging

from server.repositories.assignment_repo import AssignmentRepository
from server.repositories.film_repo import FilmRepository
from server.repositories.login_link_repo import LoginLinkRepository
from server.repositories.rating_repo import RatingRepository
from server.repositories.session_repo import SessionRepository
from server.repositories.user_repo import UserRepository

from server.services.ia_service import InternetArchiveService
from server.services.distribution_service import DistributionService
from server.services.import_service import ImportService
from server.services.job_service import JobService
from server.services.login_link_service import LoginLinkService
from server.services.ranking_service import RankingService
from server.services.rating_service import RatingService
from server.services.summary_service import SummaryService

# Blueprints
from server.routes.admin import admin_bp
from server.routes.auth import auth_bp, limiter as auth_limiter
from server.routes.films import films_bp
from server.routes.user import user_bp

logger = logging.getLogger(__name__)


# Request-body limits. Everything the app accepts is small JSON except these admin
# uploads; Flask would otherwise read any size into memory (even before login).
MAX_BODY_BYTES = 1 * 1024 * 1024
_LARGE_BODY_LIMITS = {
    "admin.import_preview": 16 * 1024 * 1024,   # CSV text (2 MB max once decoded) inside JSON
    "admin.import_films": 16 * 1024 * 1024,
    "admin.db_restore": 64 * 1024 * 1024,        # a whole-database backup
}


def create_app(settings: "Settings | None" = None, dev: bool = False) -> Flask:
    """Create and configure the Flask app.

    All configuration and dependency construction happens here (NOT at import time)
    so pytest and other importers behave predictably.

    Pass a Settings instance to override defaults (useful for tests).

    `dev=True` is for the local development entrypoint only (`python -m server.app`):
    sessions get a random per-process secret when SESSION_SECRET is unset, and the
    cookie isn't marked Secure so it works over plain http://localhost. Everywhere
    else (gunicorn, tests) SESSION_SECRET is required.
    """

    configure_logging()
    if settings is None:
        settings = load_settings()

    # The development default is public (it is in the repo), so a server using it would
    # accept forged admin sessions. Never run with it: refuse to start, except that the
    # local dev entrypoint swaps in a random secret.
    if settings.session_secret == _DEV_SECRET:
        if not dev:
            raise RuntimeError(
                "SESSION_SECRET is not set. Set it to a long random value, e.g. "
                "python3 -c \"import secrets; print(secrets.token_hex(32))\""
            )
        settings = dataclasses.replace(settings, session_secret=secrets.token_hex(32))
        logger.info("SESSION_SECRET not set: using a random per-process secret (sessions reset on restart)")

    # --- Serve the built React client (client/dist) directly from Flask ---
    repo_root = Path(__file__).resolve().parents[1]
    client_dist = repo_root / "client" / "dist"

    if client_dist.exists():
        app = Flask(__name__, static_folder=str(client_dist), static_url_path="/")
    else:
        app = Flask(__name__)

    app.secret_key = settings.session_secret
    app.config["DB_PATH"] = settings.db_path

    # M4 + M5: Secure session cookie settings.
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    # Only send the cookie over HTTPS in production (not on localhost dev).
    app.config["SESSION_COOKIE_SECURE"] = not dev
    app.config["MAX_CONTENT_LENGTH"] = MAX_BODY_BYTES
    if settings.trusted_proxy_hops:
        # Trust exactly that many proxy hops for the client address and scheme.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=settings.trusted_proxy_hops, x_proto=settings.trusted_proxy_hops)

    # --- Database + repos ---
    # Raises LegacyDatabaseError (so the server won't boot) if the file is from the old app.
    db = Database(settings.db_path)
    users = UserRepository(db)
    films = FilmRepository(db)
    assignments = AssignmentRepository(db)
    ratings = RatingRepository(db)
    sessions = SessionRepository(db)
    login_links = LoginLinkRepository(db)

    # --- Services ---
    ia = InternetArchiveService()
    jobs = JobService()
    # Film data only ever arrives through the admin's spreadsheet import; never at startup.
    importer = ImportService(films, ia, jobs)
    rating = RatingService(users, films, assignments, ratings)
    summary = SummaryService(ratings)
    links = LoginLinkService(users, login_links, sessions)
    distribution = DistributionService(users, films, assignments)
    ranking = RankingService(users, films, assignments, ratings, distribution)

    # Expose for tests / routes
    app.settings = settings
    app.db = db
    app.repos = {
        "users": users,
        "films": films,
        "assignments": assignments,
        "ratings": ratings,
        "sessions": sessions,
        "login_links": login_links,
    }
    app.services = {
        "ia": ia,
        "jobs": jobs,
        "import": importer,
        "rating": rating,
        "summary": summary,
        "links": links,
        "distribution": distribution,
        "ranking": ranking,
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

    @app.before_request
    def _body_limit():
        # Per-route override of MAX_CONTENT_LENGTH for the few admin uploads.
        limit = _LARGE_BODY_LIMITS.get(request.endpoint)
        if limit:
            request.max_content_length = limit

    # --- Error handling ---
    @app.errorhandler(413)
    def _too_large(err):
        return jsonify({"error": "Request body is too large"}), 413

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
    # The one client-side route: the magic-link page (the secret is in the URL fragment).
    # Needs its own rule because the static route at "/" answers 404 for unknown paths
    # before the catch-all below is reached.
    @app.get("/")
    @app.get("/signin")
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


def _is_loopback(host: str) -> bool:
    return host in ("127.0.0.1", "localhost", "::1")


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
    env_host = os.getenv("FLASK_RUN_HOST", "127.0.0.1")
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
    if debug and not _is_loopback(host):
        # Werkzeug's debugger runs arbitrary code for anyone who can reach it.
        raise SystemExit(f"Refusing to run with the debugger on a non-local address ({host}). Use --host 127.0.0.1 or drop --debug.")

    chosen_port = _pick_available_port(host, port)
    if chosen_port != port:
        print(f"Port {port} is busy; falling back to {chosen_port}.")

    if args.with_client:
        repo_root = Path(__file__).resolve().parents[1]
        _build_client(repo_root)

    try:
        app = create_app(settings=load_settings(), dev=True)
    except LegacyDatabaseError as exc:
        raise SystemExit(str(exc))
    app.run(host=host, port=chosen_port, debug=debug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
