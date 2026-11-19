import json
import re
import sqlite3
from datetime import datetime, timezone
from flask import Blueprint, jsonify, current_app, Response, session, request

from ..repositories.user_repo import ROLE_COLUMNS
from ..services import import_service

admin_bp = Blueprint("admin", __name__)

# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

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

def _list_tables(conn):
    return [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()]

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
            base = "SELECT id, email, ia_username, github_username, is_admin, is_judge, created_at FROM users"
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
    if user_id == int(session["user_id"]) and "admin" not in roles:
        return jsonify({"error": "You can't remove your own admin role"}), 400
    users.set_roles(user_id, roles)
    return jsonify({"ok": True, "user_id": user_id, "roles": users.roles_of(users.get_by_id(user_id))})

# ---------------------------------------------------------------------------
# Backup / restore
# ---------------------------------------------------------------------------

# Tables in dependency order for restore (parents before children).
_RESTORE_ORDER = [
    "schema_migrations",
    "app_settings",
    "users",
    "criteria",
    "films",
    "ratings",
    "rating_scores",
    "film_notes",
]

BACKUP_FORMAT_VERSION = 1


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

    tables_data = backup.get("tables")
    if not isinstance(tables_data, dict):
        return jsonify({"error": "Invalid backup: 'tables' must be an object"}), 400

    conn = _db_conn()
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        restored = {}
        try:
            with conn:  # single atomic transaction — rolls back on any exception
                # Notes point at film ids. A backup that replaces films but has no notes
                # (e.g. made before notes existed) would leave them attached to the wrong films.
                if tables_data.get("films") is not None and tables_data.get("film_notes") is None:
                    conn.execute("DELETE FROM film_notes")
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

        return jsonify({
            "ok": True,
            "exported_at": backup.get("exported_at"),
            "schema_version": backup.get("schema_version"),
            "restored": restored,
        })
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Criteria management
# ---------------------------------------------------------------------------

@admin_bp.get("/api/admin/criteria")
def list_criteria():
    """List all criteria (including inactive)."""
    ok, err = _require_admin_user()
    if err:
        return err
    criteria = current_app.repos["criteria"]
    rows = criteria.list_all()
    return jsonify([dict(r) for r in rows])


@admin_bp.post("/api/admin/criteria")
def create_criterion():
    """Create a new criterion."""
    ok, err = _require_admin_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    key       = (data.get("key") or "").strip()
    label     = (data.get("label") or "").strip()
    min_score = data.get("min_score", 1)
    max_score = data.get("max_score", 5)
    sort_order = data.get("sort_order", 0)
    active    = int(bool(data.get("active", True)))

    if not key:
        return jsonify({"error": "key is required"}), 400
    if not label:
        return jsonify({"error": "label is required"}), 400
    if not isinstance(min_score, int) or not isinstance(max_score, int):
        return jsonify({"error": "min_score and max_score must be integers"}), 400
    if min_score >= max_score:
        return jsonify({"error": "min_score must be less than max_score"}), 400

    try:
        current_app.repos["criteria"].insert(key, label, min_score, max_score, sort_order, active)
    except sqlite3.IntegrityError:
        return jsonify({"error": f"A criterion with key '{key}' already exists"}), 409
    except Exception:
        current_app.logger.exception("Failed to create criterion")
        return jsonify({"error": "Failed to create criterion"}), 500
    return jsonify({"ok": True}), 201


@admin_bp.put("/api/admin/criteria/<int:cid>")
def update_criterion(cid: int):
    """Update an existing criterion."""
    ok, err = _require_admin_user()
    if err:
        return err
    criteria = current_app.repos["criteria"]
    row = criteria.get_by_id(cid)
    if not row:
        return jsonify({"error": f"Criterion not found: {cid}"}), 404

    data = request.get_json(silent=True) or {}
    label      = (data.get("label") or row["label"]).strip()
    min_score  = data.get("min_score",  row["min_score"])
    max_score  = data.get("max_score",  row["max_score"])
    sort_order = data.get("sort_order", row["sort_order"])
    active     = int(bool(data.get("active", bool(row["active"]))))

    if not label:
        return jsonify({"error": "label is required"}), 400
    if min_score >= max_score:
        return jsonify({"error": "min_score must be less than max_score"}), 400

    criteria.update(cid, label, min_score, max_score, sort_order, active)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Film / ratings management
# ---------------------------------------------------------------------------

def _sync_status_payload() -> dict:
    payload = current_app.services["sync"].status()
    payload["film_count"] = current_app.repos["films"].count()
    return payload


@admin_bp.post("/api/admin/sync")
def sync():
    """Start an Internet Archive sync in the background; poll /api/admin/sync/status."""
    ok, err = _require_admin_user()
    if err:
        return err
    if not current_app.services["sync"].start():
        return jsonify({"error": "A sync is already running", "status": _sync_status_payload()}), 409
    return jsonify({"ok": True, "status": _sync_status_payload()}), 202


@admin_bp.get("/api/admin/sync/status")
def sync_status():
    ok, err = _require_admin_user()
    if err:
        return err
    return jsonify(_sync_status_payload())


@admin_bp.post("/api/admin/db/empty")
def empty_db():
    """Delete all films and all ratings (users and criteria are kept).

    DESTRUCTIVE. The body must be {"confirm": "EMPTY"} so a stray request can't
    wipe the data. Refused while a sync is running.
    """
    ok, err = _require_admin_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    if data.get("confirm") != "EMPTY":
        return jsonify({"error": 'Send {"confirm": "EMPTY"} to empty the database'}), 400
    if current_app.services["sync"].is_running():
        return jsonify({"error": "Wait for the running sync to finish first"}), 409
    deleted = current_app.repos["films"].delete_all_with_ratings()
    current_app.logger.warning("admin.db.emptied user_id=%s deleted=%s", session.get("user_id"), deleted)
    return jsonify({"ok": True, "deleted": deleted})

# ---------------------------------------------------------------------------
# Settings: the active film collection
# ---------------------------------------------------------------------------

def _collection_payload() -> dict:
    app_settings = current_app.repos["settings"]
    return {
        "collection": app_settings.get_collection(),
        "default_collection": app_settings.default_collection,
        "collections": app_settings.collections_in_use(),
    }


@admin_bp.get("/api/admin/settings")
def get_settings():
    """The active collection, the built-in default, and every collection that has films."""
    ok, err = _require_admin_user()
    if err:
        return err
    return jsonify(_collection_payload())


@admin_bp.put("/api/admin/settings/collection")
def set_collection():
    """Change the archive.org collection raters see and sync/import use.

    Films already in the database under another collection are kept but hidden from
    raters until that collection is selected again. Refused while a sync or title
    lookup is running (they act on the collection).
    """
    ok, err = _require_admin_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    if current_app.services["sync"].is_running():
        return jsonify({"error": "Wait for the running sync / title lookup to finish first"}), 409
    try:
        current_app.repos["settings"].set_collection(data.get("collection") or "")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    current_app.logger.warning(
        "admin.collection.changed user_id=%s collection=%s", session.get("user_id"), current_app.repos["settings"].get_collection()
    )
    return jsonify({"ok": True, **_collection_payload(), "film_count": current_app.repos["films"].count()})


# ---------------------------------------------------------------------------
# Populate films from a spreadsheet (CSV) instead of syncing from archive.org
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
        "collection": current_app.repos["settings"].get_collection(),
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
    app_settings = current_app.repos["settings"]
    active = app_settings.get_collection()
    if not dry_run:
        if on_existing not in ("skip", "update"):
            return jsonify({"error": 'on_existing must be "skip" or "update"'}), 400
        if current_app.services["sync"].is_running():
            return jsonify({"error": "Wait for the running sync / title lookup to finish first"}), 409
    try:
        # The collection the films are put in; defaults to the active one.
        collection = app_settings.validate_collection(data["collection"]) if data.get("collection") else active
        headers, rows, mapping = _parse_import_request(data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    importer = current_app.services["import"]
    items = importer.build_plan(headers, rows, mapping, collection)
    summary = importer.summarize(items)
    skipped = importer.skipped_rows(items)
    if dry_run:
        return jsonify({
            "ok": True, "dry_run": True, "summary": summary, "skipped": skipped,
            "samples": importer.samples(items), "collection": collection, "active_collection": active,
        })
    if summary["new"] + summary["existing"] == 0:
        return jsonify({"error": "No rows with an archive.org link to import", "summary": summary, "skipped": skipped}), 400
    result = importer.run(items, on_existing, bool(data.get("lookup_titles")), collection)
    # Optionally make the imported collection the one raters see.
    activated = bool(data.get("activate_collection")) and collection != active
    if activated:
        app_settings.set_collection(collection)
    result = {**result, "collection": collection, "activated": activated}
    current_app.logger.info("admin.import user_id=%s result=%s", session.get("user_id"), result)
    return jsonify({"ok": True, "result": result, "summary": summary, "skipped": skipped})


@admin_bp.get("/api/admin/notes.csv")
def notes_csv():
    """Judges' notes for the active collection as a CSV download (admin only)."""
    ok, err = _require_admin_user()
    if err:
        return err
    return Response(
        current_app.services["notes"].export_csv(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="notes.csv"'},
    )


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
