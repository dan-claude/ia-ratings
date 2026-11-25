"""The baseline schema (one clean version, no migration history) and the refusal to
start on a database made by the old app."""
import sqlite3

import pytest

from server.db import Database, LegacyDatabaseError, SCHEMA_VERSION
from server.tests.helpers import seed_film, make_user

EXPECTED_TABLES = {
    "schema_migrations", "users", "login_links", "user_sessions",
    "films", "assignments", "ratings", "rating_scores",
}


def tables(db):
    return {r["name"] for r in db.fetchall("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def test_fresh_database_has_exactly_the_baseline_tables(tmp_path):
    db = Database(str(tmp_path / "n.db"))
    assert tables(db) == EXPECTED_TABLES
    assert db.fetchone("SELECT MAX(version) AS v, COUNT(*) AS n FROM schema_migrations")["v"] == SCHEMA_VERSION == 1
    assert db.fetchone("SELECT COUNT(*) AS n FROM schema_migrations")["n"] == 1


def test_no_seed_data(tmp_path):
    db = Database(str(tmp_path / "n.db"))
    for t in EXPECTED_TABLES - {"schema_migrations"}:
        assert db.fetchone(f"SELECT COUNT(*) AS n FROM {t}")["n"] == 0


def test_reopening_is_a_no_op(tmp_path):
    path = str(tmp_path / "n.db")
    Database(path)
    db = Database(path)
    assert tables(db) == EXPECTED_TABLES
    assert db.fetchone("SELECT COUNT(*) AS n FROM schema_migrations")["n"] == 1


def test_users_have_the_three_independent_role_flags(tmp_path):
    db = Database(str(tmp_path / "n.db"))
    cols = {r["name"] for r in db.fetchall("PRAGMA table_info(users)")}
    assert {"email", "password_hash", "is_admin", "is_reviewer", "is_judge", "created_at"} <= cols
    assert not cols & {"ia_username", "github_id", "github_username"}


def test_films_have_the_spreadsheet_fields_and_no_collection(tmp_path):
    db = Database(str(tmp_path / "n.db"))
    cols = {r["name"] for r in db.fetchall("PRAGMA table_info(films)")}
    assert {"ia_identifier", "title", "creator", "description", "public_domain_works", "ai_disclosure",
            "in_judges_pool"} <= cols
    assert not cols & {"collection", "mediatype", "metadata_json"}


# ---- the old app's databases are refused ---------------------------------------------------

def make_old_database(path, version=9, with_criteria=True):
    conn = sqlite3.connect(path)
    conn.executescript("""
      CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')));
      CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0, is_judge INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now')));
      CREATE TABLE films (id INTEGER PRIMARY KEY AUTOINCREMENT, ia_identifier TEXT NOT NULL, collection TEXT NOT NULL);
    """)
    if with_criteria:
        conn.execute("CREATE TABLE criteria (id INTEGER PRIMARY KEY, key TEXT)")
    for v in range(1, version + 1):
        conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (v,))
    conn.commit()
    conn.close()


@pytest.mark.parametrize("kwargs", [
    {"version": 9, "with_criteria": True},    # a production database
    {"version": 9, "with_criteria": False},   # old users layout, old version number
    {"version": 1, "with_criteria": True},    # very old
    {"version": 1, "with_criteria": False},   # looks like version 1 but users has no is_reviewer
])
def test_old_database_is_refused_with_a_clear_message(tmp_path, kwargs):
    path = str(tmp_path / "old.db")
    make_old_database(path, **kwargs)
    with pytest.raises(LegacyDatabaseError) as exc:
        Database(path)
    msg = str(exc.value)
    assert "delete the file" in msg and path in msg
    # and it was left untouched
    conn = sqlite3.connect(path)
    assert "login_links" not in {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    conn.close()


def test_a_database_with_unrelated_tables_is_refused(tmp_path):
    path = str(tmp_path / "other.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE something_else (x)")
    conn.commit(); conn.close()
    with pytest.raises(LegacyDatabaseError):
        Database(path)


def test_a_newer_schema_version_is_refused(tmp_path):
    path = str(tmp_path / "n.db")
    db = Database(path)
    conn = db.connect()
    conn.execute("INSERT INTO schema_migrations (version) VALUES (2)")
    conn.commit(); conn.close()
    with pytest.raises(LegacyDatabaseError):
        Database(path)


def test_the_app_refuses_to_start_on_an_old_database(monkeypatch, tmp_path):
    import importlib
    path = str(tmp_path / "old.db")
    make_old_database(path)
    monkeypatch.setenv("DB_PATH", path)
    monkeypatch.setenv("SESSION_SECRET", "s")
    import server.app as m
    importlib.reload(m)
    with pytest.raises(LegacyDatabaseError):
        m.create_app()
    # the dev entrypoint turns it into a plain exit message
    monkeypatch.setattr(m, "_pick_available_port", lambda h, p: p)
    with pytest.raises(SystemExit, match="delete the file"):
        m.main([])


# ---- constraints ---------------------------------------------------------------------------

def test_constraints_reject_bad_rows(app):
    _, uid = make_user(app, "a@example.com")
    fid = seed_film(app, "f1")
    conn = app.db.connect()
    conn.execute("INSERT INTO ratings (user_id, film_id) VALUES (?, ?)", (uid, fid))
    bad = [
        "INSERT INTO rating_scores (rating_id, category, score) VALUES (1, 'appeal', 0)",
        "INSERT INTO rating_scores (rating_id, category, score) VALUES (1, 'appeal', 11)",
        f"INSERT INTO ratings (user_id, film_id) VALUES ({uid}, {fid})",                                 # one per person per film
        f"INSERT INTO ratings (user_id, film_id, comment) VALUES ({uid}, {fid + 1}, '{'x' * 1001}')",   # too long (and no such film)
        f"INSERT INTO assignments (user_id, film_id, status) VALUES ({uid}, {fid}, 'done')",
        "INSERT INTO films (ia_identifier) VALUES ('f1')",                                                 # unique identifier
        f"INSERT INTO assignments (user_id, film_id, round) VALUES ({uid}, {fid}, 'finals')",
        "INSERT INTO users (email, is_judge) VALUES ('z@example.com', 2)",
        "INSERT INTO assignments (user_id, film_id) VALUES (999, 1)",                                      # foreign key
    ]
    for sql in bad:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(sql)
    conn.close()


def test_one_active_login_link_per_user(app):
    _, uid = make_user(app, "a@example.com")
    conn = app.db.connect()
    conn.execute("INSERT INTO login_links (token_hash, user_id, expires_at) VALUES ('a', ?, '2999-01-01')", (uid,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO login_links (token_hash, user_id, expires_at) VALUES ('b', ?, '2999-01-01')", (uid,))
    conn.execute("UPDATE login_links SET revoked_at = datetime('now')")
    conn.execute("INSERT INTO login_links (token_hash, user_id, expires_at) VALUES ('b', ?, '2999-01-01')", (uid,))
    conn.close()
