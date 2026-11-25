import json
import re
from datetime import datetime, timezone
from flask import Blueprint, jsonify, current_app, Response, session, request

from ..auth_session import current_user_id
from ..db import SCHEMA_VERSION
from ..repositories.user_repo import ROLE_COLUMNS
from ..services.distribution_service import DistributionError
from ..services.ranking_service import PoolError
from ..services import import_service

admin_bp = Blueprint("admin", __name__)

# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def _require_admin_user():
    uid = current_user_id()
    if not uid:
        return False, (jsonify({"error": "Not logged in"}), 401)
    users = current_app.repos["users"]
    row = users.get_by_id(uid)
    if not row:
        return False, (jsonify({"error": "Not logged in"}), 401)
    if not ("is_admin" in row.keys() and bool(row["is_admin"])):
        return False, (jsonify({"error": "Forbidden"}), 403)
    return True, None

# ---------------------------------------------------------------------------
# DB inspection routes  (mirrors tools/print_db.py)
# ---------------------------------------------------------------------------

def _db_conn():
    """Return a raw sqlite3 connection to the app database."""
    import sqlite3
    conn = sqlite3.connect(current_app.config["DB_PATH"])
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

# Internal tables that must never be dumped, browsed or backed up (live logins and magic links).
_HIDDEN_TABLES = {"user_sessions", "login_links"}


def _list_tables(conn):
    return [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall() if r[0] not in _HIDDEN_TABLES]

@admin_bp.get("/api/admin/db/tables")
def db_tables():
    """List all tables with row counts."""
    ok, err = _require_admin_user()
    if err:
        return err
    conn = _db_conn()
    try:
        tables = _list_tables(conn)
        result = {}
        for t in tables:
            row = conn.execute(f"SELECT COUNT(1) AS n FROM {t}").fetchone()
            result[t] = int(row["n"]) if row else 0
        return jsonify(result)
    finally:
        conn.close()

@admin_bp.get("/api/admin/db/schema")
def db_schema():
    """Return CREATE TABLE statements for all user tables."""
    ok, err = _require_admin_user()
    if err:
        return err
    conn = _db_conn()
    try:
        tables = _list_tables(conn)
        schema = {}
        for t in tables:
            row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (t,)
            ).fetchone()
            schema[t] = row["sql"] if row else None
        return jsonify(schema)
    finally:
        conn.close()

_ORDER_BY_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*(\s+(ASC|DESC))?$", re.IGNORECASE)


@admin_bp.get("/api/admin/db/<table>")
def db_table(table: str):
    """
    Dump rows from any table.  Query params:
      order_by  — column name with optional ASC/DESC (e.g. "id DESC")
      limit     — integer row limit
      offset    — integer row offset

    Note: freeform WHERE is intentionally not supported to prevent SQL injection.
    Use the purpose-built endpoints (e.g. /api/admin/users) for filtered views.
    """
    ok, err = _require_admin_user()
    if err:
        return err
    conn = _db_conn()
    try:
        allowed = set(_list_tables(conn))
        if table not in allowed:
            return jsonify({"error": f"Unknown table: {table}"}), 404

        order_by = request.args.get("order_by", "").strip()
        limit    = request.args.get("limit", type=int)
        offset   = request.args.get("offset", type=int)

        # H1: Validate order_by to only allow a column name + optional ASC/DESC.
        if order_by and not _ORDER_BY_RE.match(order_by):
            return jsonify({"error": "order_by must be a column name with optional ASC/DESC"}), 400

        # For the films table, include a per-film rating count.
        # L5: For the users table, exclude the password_hash column.
        if table == "films":
            base = (
                "SELECT *, "
                "(SELECT COUNT(*) FROM ratings WHERE film_id = films.id) AS rating_count "
                "FROM films"
            )
        elif table == "users":
            base = "SELECT id, email, is_admin, is_reviewer, is_judge, created_at FROM users"
        else:
            base = f"SELECT * FROM {table}"

        sql = base
        params: list = []
        if order_by:
            sql += f" ORDER BY {order_by}"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        if offset is not None:
            sql += " OFFSET ?"
            params.append(offset)

        rows = conn.execute(sql, params).fetchall()
        return jsonify([{k: r[k] for k in r.keys()} for r in rows])
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# User admin actions  (mirrors --make-admin / --revoke-admin in print_db.py)
# ---------------------------------------------------------------------------

@admin_bp.get("/api/admin/users")
def list_users():
    """Every user with their roles and the state of their sign-in link (none / active / expired)."""
    ok, err = _require_admin_user()
    if err:
        return err
    return jsonify(current_app.services["links"].list_users())


@admin_bp.post("/api/admin/users")
def invite_user():
    """Invite a person: create their account (with roles) and their first sign-in link.

    The link is returned once and cannot be shown again (only its hash is stored); the admin
    passes it on, the app sends no email.
    """
    ok, err = _require_admin_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    roles = data.get("roles", [])
    if not isinstance(roles, list) or not all(isinstance(r, str) for r in roles):
        return jsonify({"error": "roles must be a list of role names"}), 400
    unknown = [r for r in roles if r not in ROLE_COLUMNS]
    if unknown:
        return jsonify({"error": f"Unknown role: {unknown[0]}"}), 400
    email = data.get("email")
    if not isinstance(email, str):
        return jsonify({"error": "email is required"}), 400
    try:
        res = current_app.services["links"].invite(email, list(dict.fromkeys(roles)), data.get("expires_at"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except KeyError as exc:
        return jsonify({"error": exc.args[0]}), 409
    current_app.logger.info("admin.invite user_id=%s invited=%s", session.get("user_id"), res["user_id"])
    return jsonify({"ok": True, "user": {"id": res["user_id"], "email": res["email"], "roles": res["roles"]}, "link": res["link"]}), 201


@admin_bp.post("/api/admin/users/<int:user_id>/login-link")
def new_login_link(user_id: int):
    """A new sign-in link for a user. The old link stops working and the person is logged out
    everywhere (except the admin's own current login, when it is their own link)."""
    ok, err = _require_admin_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        link = current_app.services["links"].reissue(user_id, data.get("expires_at"), _own_sid(user_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    current_app.logger.info("admin.login_link.issued user_id=%s target=%s", session.get("user_id"), user_id)
    return jsonify({"ok": True, "user_id": user_id, "link": link}), 201


@admin_bp.put("/api/admin/users/<int:user_id>/login-link")
def change_login_link_expiry(user_id: int):
    """Change the expiry of the user's active link."""
    ok, err = _require_admin_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        expires_at = current_app.services["links"].change_expiry(user_id, data.get("expires_at"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    return jsonify({"ok": True, "user_id": user_id, "expires_at": expires_at})


@admin_bp.delete("/api/admin/users/<int:user_id>/login-link")
def cancel_login_link(user_id: int):
    """Cancel the user's link and end their current logins."""
    ok, err = _require_admin_user()
    if err:
        return err
    try:
        current_app.services["links"].cancel(user_id, _own_sid(user_id))
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    current_app.logger.info("admin.login_link.cancelled user_id=%s target=%s", session.get("user_id"), user_id)
    return jsonify({"ok": True, "user_id": user_id})


def _own_sid(target_user_id: int):
    """The admin's own session id when they act on themselves (so they aren't logged out of the panel)."""
    return session.get("sid") if current_user_id() == target_user_id else None


@admin_bp.post("/api/admin/users/<int:user_id>/make-admin")
def make_admin(user_id: int):
    ok, err = _require_admin_user()
    if err:
        return err
    users = current_app.repos["users"]
    row = users.get_by_id(user_id)
    if not row:
        return jsonify({"error": f"User not found: {user_id}"}), 404
    users.set_admin(user_id, True)
    return jsonify({"ok": True, "user_id": user_id, "is_admin": True})

@admin_bp.post("/api/admin/users/<int:user_id>/revoke-admin")
def revoke_admin(user_id: int):
    ok, err = _require_admin_user()
    if err:
        return err
    users = current_app.repos["users"]
    row = users.get_by_id(user_id)
    if not row:
        return jsonify({"error": f"User not found: {user_id}"}), 404
    users.set_admin(user_id, False)
    return jsonify({"ok": True, "user_id": user_id, "is_admin": False})

@admin_bp.put("/api/admin/users/<int:user_id>/roles")
def set_roles(user_id: int):
    """Set a user's roles to exactly the given list (checkboxes in the admin UI)."""
    ok, err = _require_admin_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    roles = data.get("roles")
    if not isinstance(roles, list) or not all(isinstance(r, str) for r in roles):
        return jsonify({"error": "roles must be a list of role names"}), 400
    users = current_app.repos["users"]
    unknown = [r for r in roles if r not in ROLE_COLUMNS]
    if unknown:
        return jsonify({"error": f"Unknown role: {unknown[0]}"}), 400
    row = users.get_by_id(user_id)
    if not row:
        return jsonify({"error": f"User not found: {user_id}"}), 404
    # Don't let admins lock themselves out of the admin panel.
    if user_id == current_user_id() and "admin" not in roles:
        return jsonify({"error": "You can't remove your own admin role"}), 400
    users.set_roles(user_id, roles)
    return jsonify({"ok": True, "user_id": user_id, "roles": users.roles_of(users.get_by_id(user_id))})

# ---------------------------------------------------------------------------
# Backup / restore
# ---------------------------------------------------------------------------

# Tables in dependency order for restore (parents before children).
_RESTORE_ORDER = [
    "schema_migrations",
    "users",
    "films",
    "assignments",
    "ratings",
    "rating_scores",
]

# Tables that point at users and/or films: restoring either of those without also
# restoring these would leave rows attached to the wrong people or films.
_DEPENDENT_TABLES = ("assignments", "ratings", "rating_scores")

# 2 = the layout after the "major changes" rewrite; backups of the old app (1) can't be restored.
BACKUP_FORMAT_VERSION = 2


@admin_bp.get("/api/admin/db/backup")
def db_backup():
    """Export the entire database as a versioned JSON file."""
    ok, err = _require_admin_user()
    if err:
        return err
    conn = _db_conn()
    try:
        # Resolve schema version from migrations table.
        try:
            row = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
            schema_version = int(row["v"]) if row and row["v"] is not None else 0
        except Exception:
            schema_version = 0

        exported_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        tables = _list_tables(conn)
        tables_data = {}
        for t in tables:
            rows = conn.execute(f"SELECT * FROM {t}").fetchall()
            tables_data[t] = [{k: r[k] for k in r.keys()} for r in rows]

        backup = {
            "app": "ia_ratings",
            "format_version": BACKUP_FORMAT_VERSION,
            "schema_version": schema_version,
            "exported_at": exported_at,
            "tables": tables_data,
        }

        filename = f"ia_ratings_backup_{exported_at.replace(':', '-')}.json"
        return Response(
            json.dumps(backup, indent=2, ensure_ascii=False),
            mimetype="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    finally:
        conn.close()


@admin_bp.post("/api/admin/db/restore")
def db_restore():
    """
    Restore the database from a backup JSON produced by /api/admin/db/backup.
    DESTRUCTIVE: all existing rows in every restored table are replaced.
    """
    ok, err = _require_admin_user()
    if err:
        return err

    backup = request.get_json(silent=True)
    if not backup:
        return jsonify({"error": "Request body must be JSON"}), 400
    if backup.get("app") != "ia_ratings":
        return jsonify({"error": "Invalid backup: unexpected app identifier"}), 400
    if backup.get("format_version") != BACKUP_FORMAT_VERSION:
        return jsonify({"error": f"Unsupported format_version: {backup.get('format_version')}"}), 400

    if backup.get("schema_version") != SCHEMA_VERSION:
        return jsonify({"error": f"Unsupported schema_version: {backup.get('schema_version')}"}), 400

    tables_data = backup.get("tables")
    if not isinstance(tables_data, dict):
        return jsonify({"error": "Invalid backup: 'tables' must be an object"}), 400

    # A restore replaces the users table, so ids can end up belonging to different people.
    # Every login session is therefore revoked; the admin doing the restore keeps theirs
    # only if their account (same id and email) is still there afterwards.
    keep_sid = session.get("sid")
    keep_uid = current_user_id()
    keep_row = current_app.repos["users"].get_by_id(keep_uid) if keep_uid else None
    keep_email = keep_row["email"] if keep_row else None

    conn = _db_conn()
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        restored = {}
        try:
            with conn:  # single atomic transaction — rolls back on any exception
                conn.execute("DELETE FROM user_sessions")
                conn.execute("DELETE FROM login_links")  # they point at user ids, which the restore replaces
                # A backup that replaces users or films but lacks a dependent table would leave
                # that table's rows attached to the wrong people or films.
                if tables_data.get("films") is not None or tables_data.get("users") is not None:
                    for dep in _DEPENDENT_TABLES:
                        if tables_data.get(dep) is None:
                            conn.execute(f"DELETE FROM {dep}")
                for table in _RESTORE_ORDER:
                    rows = tables_data.get(table)
                    if rows is None:
                        continue  # table not in backup — leave as-is
                    conn.execute(f"DELETE FROM {table}")
                    if not rows:
                        restored[table] = 0
                        continue
                    # M2: Validate column names against the real schema before use.
                    actual_cols = {
                        r["name"]
                        for r in conn.execute(f"PRAGMA table_info({table})").fetchall()
                    }
                    given_cols = set(rows[0].keys())
                    unknown = given_cols - actual_cols
                    if unknown:
                        raise ValueError(
                            f"Backup contains unknown columns for table '{table}': {sorted(unknown)}"
                        )
                    cols = [c for c in rows[0].keys() if c in actual_cols]
                    placeholders = ", ".join("?" * len(cols))
                    col_names = ", ".join(f'"{c}"' for c in cols)
                    for r in rows:
                        conn.execute(
                            f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})",
                            [r.get(c) for c in cols],
                        )
                    # Keep SQLite AUTOINCREMENT sequences consistent.
                    ids = [r["id"] for r in rows if r.get("id") is not None]
                    if ids:
                        conn.execute(
                            "INSERT OR REPLACE INTO sqlite_sequence (name, seq) VALUES (?, ?)",
                            (table, max(ids)),
                        )
                    restored[table] = len(rows)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        finally:
            conn.execute("PRAGMA foreign_keys = ON")

        sessions = current_app.repos["sessions"]
        if keep_sid and keep_uid and keep_email:
            after = current_app.repos["users"].get_by_id(keep_uid)
            if after and after["email"] == keep_email:
                sessions.create(keep_uid, sid=keep_sid)
        return jsonify({
            "ok": True,
            "exported_at": backup.get("exported_at"),
            "schema_version": backup.get("schema_version"),
            "restored": restored,
        })
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Handing films out to reviewers, and progress
# ---------------------------------------------------------------------------

@admin_bp.get("/api/admin/progress")
def progress():
    """How far reviewing has got: overall counter, one row per person, one row per film."""
    ok, err = _require_admin_user()
    if err:
        return err
    return jsonify(current_app.services["distribution"].progress())


@admin_bp.post("/api/admin/distribute")
def distribute():
    """Give every film to two different reviewers, chosen at random. Runs once (409 if films
    have already been handed out; reset first)."""
    ok, err = _require_admin_user()
    if err:
        return err
    try:
        result = current_app.services["distribution"].distribute()
    except DistributionError as exc:
        return jsonify({"error": str(exc), "code": exc.code}), 409
    current_app.logger.warning("admin.distribute user_id=%s result=%s", session.get("user_id"), result)
    return jsonify({"ok": True, **result})


@admin_bp.post("/api/admin/distribute/reset")
def distribute_reset():
    """**Destructive.** Delete every assignment and every rating, and clear the judges' pool, so
    the films can be handed out again. Body `{"confirm": "RESET"}`."""
    ok, err = _require_admin_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    if data.get("confirm") != "RESET":
        return jsonify({"error": 'Send {"confirm": "RESET"} to reset the distribution'}), 400
    deleted = current_app.services["distribution"].reset()
    current_app.logger.warning("admin.distribute.reset user_id=%s deleted=%s", session.get("user_id"), deleted)
    return jsonify({"ok": True, "deleted": deleted})


@admin_bp.post("/api/admin/assignments")
def assign_film():
    """Hand one film to one reviewer or judge by hand: `{"user_id": 3, "identifier": "film-a"}`."""
    ok, err = _require_admin_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    user_id, identifier = data.get("user_id"), data.get("identifier")
    if isinstance(user_id, bool) or not isinstance(user_id, int) or not isinstance(identifier, str):
        return jsonify({"error": "user_id (number) and identifier (text) are required"}), 400
    try:
        added = current_app.services["distribution"].assign(user_id, identifier)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    return jsonify({"ok": True, "added": added}), 201 if added else 200


@admin_bp.delete("/api/admin/assignments/<int:user_id>/<identifier>")
def unassign_film(user_id: int, identifier: str):
    """Take a film off a person's list (not once they have rated it: ratings are final)."""
    ok, err = _require_admin_user()
    if err:
        return err
    try:
        outcome = current_app.services["distribution"].unassign(user_id, identifier)
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    if outcome == "missing":
        return jsonify({"error": "That film is not assigned to that person"}), 404
    if outcome == "rated":
        return jsonify({"error": "They have already rated this film, so it can't be taken away"}), 409
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Rankings and the judges' pool
# ---------------------------------------------------------------------------

def _pool_error(exc: PoolError):
    return jsonify({"error": str(exc), "code": exc.code, **exc.extra}), 409


@admin_bp.get("/api/admin/rankings")
def rankings():
    """Every film with its reviewers' average score (highest first) and all its details."""
    ok, err = _require_admin_user()
    if err:
        return err
    films = [{k: v for k, v in r.items() if k != "id"} for r in current_app.services["ranking"].rankings()]
    return jsonify({"films": films, "overall": current_app.services["distribution"].progress()["overall"]})


@admin_bp.get("/api/admin/rankings.csv")
def rankings_csv():
    ok, err = _require_admin_user()
    if err:
        return err
    return Response(
        current_app.services["ranking"].rankings_csv(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="rankings.csv"'},
    )


@admin_bp.get("/api/admin/judges-pool")
def judges_pool():
    """The current judges' pool (ranked, with averages) and each judge's progress on it."""
    ok, err = _require_admin_user()
    if err:
        return err
    status = current_app.services["ranking"].pool_status()
    status["films"] = [{k: v for k, v in r.items() if k != "id"} for r in status["films"]]
    return jsonify(status)


@admin_bp.get("/api/admin/judges-pool/preview")
def judges_pool_preview():
    """The ranked list a pool of `count` films (default 20) would be, with the tie check.
    Changes nothing. 409 `reviews_missing` until every film has both of its reviews."""
    ok, err = _require_admin_user()
    if err:
        return err
    raw = request.args.get("count")
    try:
        count = None if raw is None else int(raw)
        preview = current_app.services["ranking"].preview(count)
    except PoolError as exc:
        return _pool_error(exc)
    except ValueError:
        return jsonify({"error": "count must be a whole number between 1 and the number of films"}), 400
    preview["films"] = [{k: v for k, v in r.items() if k != "id"} for r in preview["films"]]
    return jsonify(preview)


@admin_bp.post("/api/admin/judges-pool")
def confirm_judges_pool():
    """Confirm the pool: the top `count` films become the judges' pool and every judge is given
    all of them. Same checks as the preview, plus: no tie at the cut-off, and no pool yet."""
    ok, err = _require_admin_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        result = current_app.services["ranking"].confirm(data.get("count"))
    except PoolError as exc:
        return _pool_error(exc)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    current_app.logger.warning("admin.judges_pool.confirmed user_id=%s result=%s", session.get("user_id"), result)
    return jsonify({"ok": True, **result}), 201


@admin_bp.post("/api/admin/judges-pool/assign")
def assign_judges_pool():
    """Give every pool film to every judge again (idempotent; for judges added after the pool was set)."""
    ok, err = _require_admin_user()
    if err:
        return err
    try:
        return jsonify({"ok": True, **current_app.services["ranking"].assign_pool()})
    except PoolError as exc:
        return _pool_error(exc)


@admin_bp.delete("/api/admin/judges-pool")
def clear_judges_pool():
    """Clear the pool and the judges' unrated pool assignments so it can be chosen again.
    409 `judges_have_rated` once a judge has rated a pool film."""
    ok, err = _require_admin_user()
    if err:
        return err
    try:
        result = current_app.services["ranking"].clear_pool()
    except PoolError as exc:
        return _pool_error(exc)
    current_app.logger.warning("admin.judges_pool.cleared user_id=%s", session.get("user_id"))
    return jsonify({"ok": True, **result})


# ---------------------------------------------------------------------------
# Films: background jobs, emptying the database, spreadsheet import
# ---------------------------------------------------------------------------

def _job_status_payload() -> dict:
    payload = current_app.services["jobs"].status()
    payload["film_count"] = current_app.repos["films"].count()
    return payload


@admin_bp.get("/api/admin/jobs/status")
def job_status():
    """Progress of the background job (currently only the title lookup after an import)."""
    ok, err = _require_admin_user()
    if err:
        return err
    return jsonify(_job_status_payload())


@admin_bp.post("/api/admin/db/empty")
def empty_db():
    """Delete all films, assignments and ratings (users are kept).

    DESTRUCTIVE. The body must be {"confirm": "EMPTY"} so a stray request can't
    wipe the data. Refused while a background job is running.
    """
    ok, err = _require_admin_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    if data.get("confirm") != "EMPTY":
        return jsonify({"error": 'Send {"confirm": "EMPTY"} to empty the database'}), 400
    if current_app.services["jobs"].is_running():
        return jsonify({"error": "Wait for the running background job to finish first"}), 409
    deleted = current_app.repos["films"].delete_all_with_ratings()
    current_app.logger.warning("admin.db.emptied user_id=%s deleted=%s", session.get("user_id"), deleted)
    return jsonify({"ok": True, "deleted": deleted})


# ---------------------------------------------------------------------------
# Populate films from a spreadsheet (CSV)
# ---------------------------------------------------------------------------

def _parse_import_request(data: dict):
    """Return (headers, rows, mapping) from an import request body, or raise ValueError."""
    headers, rows = import_service.parse_csv(data.get("csv_text") or "")
    mapping = import_service.validate_mapping(data.get("mapping"), len(headers))
    return headers, rows, mapping


@admin_bp.post("/api/admin/import/preview")
def import_preview():
    """Read a CSV and suggest a column mapping. Saves nothing."""
    ok, err = _require_admin_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        headers, rows = import_service.parse_csv(data.get("csv_text") or "")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({
        "headers": headers,
        "row_count": len(rows),
        "sample_rows": [[c[:200] for c in cells] for _, cells in rows[:5]],
        "suggested_mapping": import_service.suggest_mapping(headers, rows),
    })


@admin_bp.post("/api/admin/import")
def import_films():
    """Import films from a CSV using a column mapping; `dry_run` only reports what would happen."""
    ok, err = _require_admin_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    dry_run = bool(data.get("dry_run"))
    on_existing = data.get("on_existing")
    if not dry_run:
        if on_existing not in ("skip", "update"):
            return jsonify({"error": 'on_existing must be "skip" or "update"'}), 400
        if current_app.services["jobs"].is_running():
            return jsonify({"error": "Wait for the running background job to finish first"}), 409
    try:
        headers, rows, mapping = _parse_import_request(data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    importer = current_app.services["import"]
    items = importer.build_plan(headers, rows, mapping)
    summary = importer.summarize(items)
    skipped = importer.skipped_rows(items)
    if dry_run:
        return jsonify({"ok": True, "dry_run": True, "summary": summary, "skipped": skipped, "samples": importer.samples(items)})
    if summary["new"] + summary["existing"] == 0:
        return jsonify({"error": "No rows with an archive.org link to import", "summary": summary, "skipped": skipped}), 400
    result = importer.run(items, on_existing, bool(data.get("lookup_titles")))
    current_app.logger.info("admin.import user_id=%s result=%s", session.get("user_id"), result)
    return jsonify({"ok": True, "result": result, "summary": summary, "skipped": skipped})


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
