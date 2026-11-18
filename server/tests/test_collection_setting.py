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
