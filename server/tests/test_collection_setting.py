"""The active film collection is an admin setting stored in the database."""
import importlib
import json

import pytest

from server.tests.helpers import register, logout

DEFAULT = "2026-public-domain-day-film-contest"
NEW = "2027-public-domain-day-film-contest"


def make_admin(app, client, email="admin@example.com"):
    register(client, email, "pw")
    u = app.repos["users"].get_by_email(email)
    app.repos["users"].set_admin(int(u["id"]), True)


def put_collection(client, value):
    return client.put("/api/admin/settings/collection", json={"collection": value})


def seed(app, ident="f1"):
    app.repos["films"].import_rows([{"identifier": ident, "title": "T", "description": None}], "skip")


def test_default_collection_until_set(app, client):
    make_admin(app, client)
    d = client.get("/api/admin/settings").get_json()
    assert d["collection"] == DEFAULT and d["default_collection"] == DEFAULT and d["collections"] == []
    assert app.db.fetchone("SELECT 1 FROM schema_migrations WHERE version = 6") is not None


def test_settings_endpoints_require_admin(app, client):
    assert client.get("/api/admin/settings").status_code == 401
    assert put_collection(client, NEW).status_code == 401
    register(client, "u@example.com", "pw")
    assert client.get("/api/admin/settings").status_code == 403
    assert put_collection(client, NEW).status_code == 403


def test_set_collection_takes_effect_everywhere_immediately(app, client, monkeypatch):
    make_admin(app, client)
    r = put_collection(client, "  " + NEW + "  ")
    assert r.status_code == 200
    d = r.get_json()
    assert d["collection"] == NEW and d["film_count"] == 0

    assert app.repos["films"].collection == NEW
    assert app.services["ia"].collection == NEW
    assert app.services["summary"].collection == NEW

    # sync searches archive.org for the NEW collection
    from server.services import ia_service
    seen = {}

    class R:
        def raise_for_status(self): pass
        def json(self): return {"response": {"docs": [], "numFound": 0}}

    monkeypatch.setattr(ia_service.requests, "get", lambda url, params=None, timeout=None: seen.update(params) or R())
    app.services["ia"]._advancedsearch(page=1, rows=10)
    assert seen["q"] == f"collection:{NEW} AND mediatype:movies"


def test_raters_only_see_films_in_the_active_collection(app, client):
    make_admin(app, client)
    seed(app, "old-film")                                    # added under the default collection
    assert client.get("/api/films/next").get_json()["identifier"] == "old-film"

    put_collection(client, NEW)
    assert client.get("/api/films/next").get_json()["code"] == "no_films"   # old films hidden, not deleted
    seed(app, "new-film")                                    # imported/synced under the new collection
    assert client.get("/api/films/next").get_json()["identifier"] == "new-film"
    assert app.repos["films"].count() == 1

    listing = client.get("/api/admin/settings").get_json()["collections"]
    assert listing == [{"name": DEFAULT, "films": 1}, {"name": NEW, "films": 1}]

    put_collection(client, DEFAULT)                          # switch back: old films return
    assert client.get("/api/films/next").get_json()["identifier"] == "old-film"


def test_csv_import_tags_films_with_the_active_collection(app, client):
    make_admin(app, client)
    put_collection(client, NEW)
    r = client.post("/api/admin/import", json={
        "csv_text": "Link\nhttps://archive.org/details/a1\n", "mapping": {"link": 0}, "on_existing": "skip",
    })
    assert r.status_code == 200
    assert app.db.fetchone("SELECT collection c FROM films WHERE ia_identifier='a1'")["c"] == NEW
    assert client.get("/api/films/next").status_code == 200
    preview = client.post("/api/admin/import/preview", json={"csv_text": "Link\nhttps://archive.org/details/a1\n"}).get_json()
    assert preview["collection"] == NEW


@pytest.mark.parametrize("bad", ["", "   ", None, "has space", "slash/inside", "-leading-dash", "x" * 101, "semi;colon", "emoji🎬"])
def test_invalid_collection_rejected_and_unchanged(app, client, bad):
    make_admin(app, client)
    assert put_collection(client, bad).status_code == 400
    assert client.get("/api/admin/settings").get_json()["collection"] == DEFAULT


def test_cannot_change_collection_while_a_job_runs(app, client, monkeypatch):
    import threading
    make_admin(app, client)
    release, started = threading.Event(), threading.Event()

    def slow(self, films_repo, progress=None, **kw):
        started.set()
        release.wait(10)
        return 0

    monkeypatch.setattr(type(app.services["ia"]), "sync_collection", slow)
    client.post("/api/admin/sync")
    assert started.wait(10)
    assert put_collection(client, NEW).status_code == 409
    assert client.get("/api/admin/settings").get_json()["collection"] == DEFAULT
    release.set()
    app.services["sync"].wait(10)
    assert put_collection(client, NEW).status_code == 200


def test_setting_survives_a_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "persist.db"))
    monkeypatch.setenv("SESSION_SECRET", "s")
    monkeypatch.setenv("AUTH_SCHEME", "local")
    import server.app as app_module
    importlib.reload(app_module)
    app1 = app_module.create_app()
    c = app1.test_client()
    make_admin(app1, c)
    put_collection(c, NEW)

    app2 = app_module.create_app()                       # new process, same database
    assert app2.repos["settings"].get_collection() == NEW
    assert app2.repos["films"].collection == NEW


def test_collection_setting_is_included_in_backup_and_restore(app, client):
    make_admin(app, client)
    put_collection(client, NEW)
    backup = json.loads(client.get("/api/admin/db/backup").data)
    assert backup["tables"]["app_settings"][0]["value"] == NEW

    put_collection(client, DEFAULT)
    assert client.post("/api/admin/db/restore", json=backup).status_code == 200
    assert app.repos["settings"].get_collection() == NEW


def test_older_database_gets_the_settings_table(tmp_path):
    import sqlite3
    from server.db import Database
    path = str(tmp_path / "old.db")
    Database(path)                                         # create current schema...
    conn = sqlite3.connect(path)
    conn.execute("DROP TABLE app_settings")
    conn.execute("DELETE FROM schema_migrations WHERE version = 6")
    conn.commit(); conn.close()
    db = Database(path)                                    # ...then 'upgrade' it
    assert db.fetchone("SELECT COUNT(1) n FROM app_settings")["n"] == 0
    assert db.fetchone("SELECT 1 FROM schema_migrations WHERE version = 6") is not None


# ---- choosing the collection while importing -----------------------------------------

CSV = "Link\nhttps://archive.org/details/a1\nhttps://archive.org/details/a2\n"


def do_import(client, **extra):
    return client.post("/api/admin/import", json={"csv_text": CSV, "mapping": {"link": 0}, "on_existing": "skip", **extra})


def test_import_into_a_chosen_collection_without_changing_the_active_one(app, client):
    make_admin(app, client)
    r = do_import(client, collection="  " + NEW + " ")
    assert r.status_code == 200
    res = r.get_json()["result"]
    assert res["collection"] == NEW and res["activated"] is False
    assert {x["collection"] for x in app.db.fetchall("SELECT collection FROM films")} == {NEW}
    # the active collection is unchanged, so raters don't see them yet
    assert client.get("/api/admin/settings").get_json()["collection"] == DEFAULT
    assert client.get("/api/films/next").get_json()["code"] == "no_films"


def test_import_can_make_its_collection_active(app, client):
    make_admin(app, client)
    r = do_import(client, collection=NEW, activate_collection=True)
    assert r.get_json()["result"]["activated"] is True
    assert client.get("/api/admin/settings").get_json()["collection"] == NEW
    assert client.get("/api/films/next").status_code == 200


def test_import_defaults_to_the_active_collection(app, client):
    make_admin(app, client)
    put_collection(client, NEW)
    do_import(client)
    assert {x["collection"] for x in app.db.fetchall("SELECT collection FROM films")} == {NEW}
    # asking to "activate" the collection that is already active is a no-op
    assert do_import(client, collection=NEW, activate_collection=True, on_existing="update").get_json()["result"]["activated"] is False


@pytest.mark.parametrize("bad", ["has space", "slash/inside", "-lead", "x" * 101, 123, ["a"], {"a": 1}])
def test_import_rejects_an_invalid_collection_name(app, client, bad):
    make_admin(app, client)
    assert do_import(client, collection=bad).status_code == 400
    assert do_import(client, collection=bad, dry_run=True).status_code == 400
    assert app.repos["films"].count() == 0
    assert client.get("/api/admin/settings").get_json()["collection"] == DEFAULT


def test_dry_run_reports_target_and_active_collections(app, client):
    make_admin(app, client)
    d = do_import(client, dry_run=True, collection=NEW).get_json()
    assert (d["collection"], d["active_collection"]) == (NEW, DEFAULT)
    d = do_import(client, dry_run=True).get_json()
    assert (d["collection"], d["active_collection"]) == (DEFAULT, DEFAULT)
    assert app.repos["films"].count() == 0


def test_existing_means_existing_in_the_target_collection(app, client):
    """Importing into a new collection: films that exist only elsewhere are NOT 'already there'."""
    make_admin(app, client)
    do_import(client)                                                   # a1, a2 -> default collection

    d = do_import(client, dry_run=True).get_json()                      # same collection: both exist
    assert d["summary"] == {"rows": 2, "new": 0, "existing": 2, "skipped": 0}
    d = do_import(client, dry_run=True, collection=NEW).get_json()      # new collection: nothing there yet
    assert d["summary"] == {"rows": 2, "new": 2, "existing": 0, "skipped": 0}
    assert all(not f["exists"] for f in d["samples"])


def test_same_item_can_live_in_two_collections_with_separate_rows(app, client):
    make_admin(app, client)
    do_import(client)
    r = do_import(client, collection=NEW)                               # on_existing=skip, but nothing exists there
    assert r.get_json()["result"]["added"] == 2 and r.get_json()["result"]["skipped_existing"] == 0

    rows = app.db.fetchall("SELECT id, ia_identifier, collection FROM films ORDER BY id")
    assert len(rows) == 4
    assert sorted((x["ia_identifier"], x["collection"]) for x in rows) == [
        ("a1", DEFAULT), ("a1", NEW), ("a2", DEFAULT), ("a2", NEW)]
    # importing the same file into the same collection again is what counts as existing
    r = do_import(client, collection=NEW).get_json()["result"]
    assert (r["added"], r["skipped_existing"]) == (0, 2)
    assert app.db.fetchone("SELECT COUNT(1) n FROM films")["n"] == 4


def test_update_only_touches_films_in_the_target_collection(app, client):
    make_admin(app, client)
    csv_text = "Title,Link\nOld,https://archive.org/details/a1\n"
    body = {"csv_text": csv_text, "mapping": {"link": 1, "title": 0}}
    client.post("/api/admin/import", json={**body, "on_existing": "skip"})                       # default collection
    client.post("/api/admin/import", json={**body, "on_existing": "skip", "collection": NEW})    # new collection
    csv2 = "Title,Link\nRenamed,https://archive.org/details/a1\n"
    r = client.post("/api/admin/import", json={"csv_text": csv2, "mapping": {"link": 1, "title": 0},
                                               "on_existing": "update", "collection": NEW})
    assert r.get_json()["result"]["updated"] == 1
    titles = {x["collection"]: x["title"] for x in app.db.fetchall("SELECT collection, title FROM films")}
    assert titles == {DEFAULT: "Old", NEW: "Renamed"}                   # the other collection's row is untouched


def test_ratings_and_lookups_are_per_collection(app, client):
    make_admin(app, client)
    do_import(client)
    do_import(client, collection=NEW)
    scores = {"originality": 4, "use_of_archive_materials": 2}
    assert client.post("/api/films/a1/ratings", json={"scores": scores}).status_code == 200   # rates the DEFAULT a1

    put_collection(client, NEW)                                         # same item, other collection: unrated there
    assert client.get("/api/films/a1").status_code == 200
    seen = {client.get("/api/films/next").get_json()["identifier"] for _ in range(20)}
    assert seen == {"a1", "a2"}                                         # both still to rate in NEW
    assert client.post("/api/films/a1/ratings", json={"scores": scores}).status_code == 200
    assert app.db.fetchone("SELECT COUNT(1) n FROM ratings")["n"] == 2  # one rating per (item, collection)
    assert len({r["film_id"] for r in app.db.fetchall("SELECT film_id FROM ratings")}) == 2


def test_sync_upsert_is_per_collection(app, client):
    make_admin(app, client)
    films = app.repos["films"]
    films.upsert_many_from_ia([{"identifier": "x", "title": "T1"}])
    put_collection(client, NEW)
    films.upsert_many_from_ia([{"identifier": "x", "title": "T2"}])     # same item, new collection -> own row
    rows = {r["collection"]: r["title"] for r in app.db.fetchall("SELECT collection, title FROM films")}
    assert rows == {DEFAULT: "T1", NEW: "T2"}
    films.upsert_many_from_ia([{"identifier": "x", "title": "T3"}])     # re-sync updates only the active row
    rows = {r["collection"]: r["title"] for r in app.db.fetchall("SELECT collection, title FROM films")}
    assert rows == {DEFAULT: "T1", NEW: "T3"}


def test_title_lookup_only_updates_the_target_collection(app, client, monkeypatch):
    make_admin(app, client)
    do_import(client)                                                   # a1, a2 in DEFAULT (title = identifier)
    monkeypatch.setattr(type(app.services["ia"]), "fetch_title", lambda self, ident: f"Looked up {ident}")
    r = do_import(client, collection=NEW, lookup_titles=True)
    assert r.get_json()["result"]["title_lookup_started"] is True
    app.services["sync"].wait(10)
    titles = {(x["ia_identifier"], x["collection"]): x["title"] for x in app.db.fetchall("SELECT ia_identifier, collection, title FROM films")}
    assert titles[("a1", NEW)] == "Looked up a1"
    assert titles[("a1", DEFAULT)] == "a1"                              # the other collection keeps its fallback title


def test_import_collection_is_refused_while_a_job_runs(app, client, monkeypatch):
    import threading
    make_admin(app, client)
    release, started = threading.Event(), threading.Event()

    def slow(self, films_repo, progress=None, **kw):
        started.set()
        release.wait(10)
        return 0

    monkeypatch.setattr(type(app.services["ia"]), "sync_collection", slow)
    client.post("/api/admin/sync")
    assert started.wait(10)
    assert do_import(client, collection=NEW, activate_collection=True).status_code == 409
    assert client.get("/api/admin/settings").get_json()["collection"] == DEFAULT
    release.set()
    app.services["sync"].wait(10)


# ---- migration v7: an old database (UNIQUE(ia_identifier)) is rebuilt without losing anything --------------

OLD_FILMS_DDL = """
CREATE TABLE films (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ia_identifier TEXT NOT NULL UNIQUE,
  title TEXT,
  description TEXT,
  collection TEXT NOT NULL,
  mediatype TEXT,
  metadata_json TEXT,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
)"""


def make_old_database(path):
    """Build the pre-v7 schema with data (films, ratings, scores) using the real current code, then
    swap films back to the old definition."""
    import sqlite3
    from server.db import Database
    Database(path)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA legacy_alter_table = ON")   # keep ratings' FOREIGN KEY pointing at "films" when renaming
    conn.execute("ALTER TABLE films RENAME TO films_current")
    conn.execute(OLD_FILMS_DDL)
    conn.execute("DROP TABLE films_current")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_films_collection ON films(collection)")
    conn.execute("DELETE FROM schema_migrations WHERE version = 7")
    conn.execute("INSERT INTO users (email, password_hash) VALUES ('u@example.com', 'x')")
    conn.executemany(
        "INSERT INTO films (id, ia_identifier, title, description, collection, mediatype, metadata_json) VALUES (?,?,?,?,?,?,?)",
        [(1, "alpha", "Alpha", "d1", DEFAULT, "movies", None), (2, "beta", "Beta", None, DEFAULT, "movies", '{"k": 1}'),
         (7, "gamma", "Gamma", "d3", "other-collection", "movies", None)])
    conn.execute("INSERT INTO ratings (id, user_id, film_id) VALUES (1, 1, 2)")
    conn.execute("INSERT INTO rating_scores (rating_id, criteria_id, score) VALUES (1, 1, 4)")
    conn.execute("DELETE FROM sqlite_sequence WHERE name = 'films'")
    conn.execute("INSERT INTO sqlite_sequence (name, seq) VALUES ('films', 7)")
    conn.commit()
    conn.close()


def test_old_database_is_rebuilt_with_unique_per_collection(tmp_path):
    import sqlite3
    from server.db import Database
    path = str(tmp_path / "old.db")
    make_old_database(path)
    pre = sqlite3.connect(path); pre.row_factory = sqlite3.Row
    assert Database._films_unique_on_identifier_only(pre) is True        # the fixture really is the old schema
    pre.close()

    db = Database(path)                                                # upgrade on startup

    assert db.fetchone("SELECT 1 FROM schema_migrations WHERE version = 7") is not None
    conn = db.connect()
    assert Database._films_unique_on_identifier_only(conn) is False
    # data and ids are preserved exactly
    rows = [tuple(r) for r in conn.execute("SELECT id, ia_identifier, title, description, collection, mediatype, metadata_json FROM films ORDER BY id")]
    assert rows == [(1, "alpha", "Alpha", "d1", DEFAULT, "movies", None),
                    (2, "beta", "Beta", None, DEFAULT, "movies", '{"k": 1}'),
                    (7, "gamma", "Gamma", "d3", "other-collection", "movies", None)]
    # ratings still point at the right film
    assert tuple(conn.execute("SELECT r.film_id, f.ia_identifier, s.score FROM ratings r JOIN films f ON f.id = r.film_id "
                              "JOIN rating_scores s ON s.rating_id = r.id").fetchone()) == (2, "beta", 4)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    # AUTOINCREMENT continues after the highest old id
    conn.execute("INSERT INTO films (ia_identifier, collection) VALUES ('delta', 'c')")
    assert conn.execute("SELECT id FROM films WHERE ia_identifier = 'delta'").fetchone()[0] == 8
    # the same identifier is now allowed in a second collection, but not twice in one
    conn.execute("INSERT INTO films (ia_identifier, collection) VALUES ('alpha', 'second')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO films (ia_identifier, collection) VALUES ('alpha', 'second')")
    conn.rollback()
    conn.close()


def test_migration_is_idempotent_and_fresh_databases_already_have_the_new_schema(tmp_path):
    import sqlite3
    from server.db import Database
    path = str(tmp_path / "fresh.db")
    Database(path)
    conn = sqlite3.connect(path); conn.row_factory = sqlite3.Row
    assert Database._films_unique_on_identifier_only(conn) is False
    n = conn.execute("SELECT COUNT(1) n FROM schema_migrations WHERE version = 7").fetchone()["n"]
    conn.close()
    assert n == 1
    Database(path); Database(path)                                      # restarts change nothing
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT COUNT(1) FROM schema_migrations WHERE version = 7").fetchone()[0] == 1
    conn.close()


def test_failed_rebuild_leaves_the_old_table_intact(tmp_path, monkeypatch):
    import sqlite3
    from server.db import Database
    path = str(tmp_path / "old.db")
    make_old_database(path)

    class FailingConn(sqlite3.Connection):
        def execute(self, sql, *a):
            if isinstance(sql, str) and sql.strip().startswith("DROP TABLE films"):
                raise sqlite3.OperationalError("simulated crash during rebuild")
            return super().execute(sql, *a)

    real_connect = sqlite3.connect
    monkeypatch.setattr(sqlite3, "connect", lambda p, *a, **k: real_connect(p, *a, factory=FailingConn, **k))
    with pytest.raises(sqlite3.OperationalError):
        Database(path)
    monkeypatch.undo()

    conn = real_connect(path)
    assert conn.execute("SELECT COUNT(1) FROM films").fetchone()[0] == 3         # nothing lost
    assert conn.execute("SELECT COUNT(1) FROM sqlite_master WHERE name = 'films_new'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(1) FROM schema_migrations WHERE version = 7").fetchone()[0] == 0
    conn.close()
    Database(path)                                                               # and a later start succeeds
