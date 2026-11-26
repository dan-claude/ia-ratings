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


# ---- LEGACY_DB=move-aside --------------------------------------------------------------

def app_with(tmp_path, monkeypatch, legacy_db=None):
    import importlib
    monkeypatch.setenv("DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("SESSION_SECRET", "s")
    if legacy_db is None:
        monkeypatch.delenv("LEGACY_DB", raising=False)
    else:
        monkeypatch.setenv("LEGACY_DB", legacy_db)
    import server.app as m
    importlib.reload(m)
    return m


def moved_files(tmp_path):
    return sorted(p.name for p in tmp_path.iterdir() if ".legacy-" in p.name)


def test_move_aside_keeps_the_old_data_and_starts_fresh(tmp_path, monkeypatch):
    path = str(tmp_path / "app.db")
    make_old_database(path)
    conn = sqlite3.connect(path); conn.execute("INSERT INTO criteria (key) VALUES ('keepme')"); conn.commit(); conn.close()
    m = app_with(tmp_path, monkeypatch, "move-aside")
    app = m.create_app()
    assert Database(path).fetchone("SELECT COUNT(*) AS n FROM users")["n"] == 0        # fresh, new-style
    assert tables(app.db) == EXPECTED_TABLES
    (old,) = moved_files(tmp_path)
    kept = sqlite3.connect(str(tmp_path / old))
    assert kept.execute("SELECT key FROM criteria").fetchone()[0] == "keepme"            # nothing was deleted
    kept.close()


def test_move_legacy_aside_moves_the_wal_and_shm_files_too(tmp_path):
    from server.db import move_legacy_aside
    path = tmp_path / "app.db"
    make_old_database(str(path))
    (tmp_path / "app.db-wal").write_bytes(b"wal"); (tmp_path / "app.db-shm").write_bytes(b"shm")
    target = move_legacy_aside(str(path))
    assert not path.exists() and not (tmp_path / "app.db-wal").exists() and not (tmp_path / "app.db-shm").exists()
    assert (tmp_path / "app.db-wal").name not in moved_files(tmp_path)
    assert open(target + "-wal", "rb").read() == b"wal" and open(target + "-shm", "rb").read() == b"shm"


def test_a_leftover_setting_does_nothing_once_the_database_is_new(tmp_path, monkeypatch):
    path = str(tmp_path / "app.db")
    make_old_database(path)
    m = app_with(tmp_path, monkeypatch, "move-aside")
    app = m.create_app()
    uid = app.repos["users"].create_user("a@example.com", ["admin"])
    for _ in range(3):                                    # every later deploy or restart
        app = m.create_app()
    assert app.repos["users"].get_by_id(uid)["email"] == "a@example.com"                 # data intact
    assert len(moved_files(tmp_path)) == 1                                              # nothing moved again


def test_without_the_setting_or_with_another_value_the_old_file_is_refused_and_left_alone(tmp_path, monkeypatch):
    path = str(tmp_path / "app.db")
    make_old_database(path)
    for value in (None, "", "delete", "yes", "1"):
        m = app_with(tmp_path, monkeypatch, value)
        with pytest.raises(LegacyDatabaseError):
            m.create_app()
    assert moved_files(tmp_path) == [] and (tmp_path / "app.db").exists()


def test_move_aside_on_a_missing_or_new_database_changes_nothing(tmp_path, monkeypatch):
    m = app_with(tmp_path, monkeypatch, "move-aside")
    m.create_app()                                        # no file yet: created fresh
    m.create_app()
    assert moved_files(tmp_path) == []


def test_two_moves_in_the_same_second_do_not_collide(tmp_path):
    from server.db import move_legacy_aside
    a = str(tmp_path / "a.db")
    for _ in range(2):
        make_old_database(a)
        move_legacy_aside(a)
    assert len(moved_files(tmp_path)) == 2
