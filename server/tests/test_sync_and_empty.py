"""Background sync + status, the empty-database command, and the 'not set up' message."""
import threading

import pytest

from server.tests.helpers import register, logout
from server.services.sync_service import SyncService


def make_admin(app, client, email="admin@example.com"):
    register(client, email, "pw")
    u = app.repos["users"].get_by_email(email)
    app.repos["users"].set_admin(int(u["id"]), True)


def seed_film(app, ident="f1"):
    app.repos["films"].upsert_many_from_ia([{"identifier": ident, "title": "T"}])


# ---- nothing syncs by itself ------------------------------------------------

def test_startup_does_not_sync(tmp_path, monkeypatch):
    import importlib
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("SESSION_SECRET", "s")
    monkeypatch.setenv("AUTH_SCHEME", "local")
    import server.app as app_module
    importlib.reload(app_module)
    from server.services.ia_service import InternetArchiveService

    def boom(*a, **k):
        raise AssertionError("sync must not run at startup")

    monkeypatch.setattr(InternetArchiveService, "sync_collection", boom)
    monkeypatch.setattr(InternetArchiveService, "iter_collection_movies", boom)
    app = app_module.create_app()
    assert app.repos["films"].count() == 0
    assert app.services["sync"].status()["state"] == "idle"


# ---- "film database not set up" --------------------------------------------

def test_next_film_reports_database_not_set_up(app, client):
    register(client, "u@example.com", "pw")
    r = client.get("/api/films/next")
    assert r.status_code == 404
    body = r.get_json()
    assert body["code"] == "no_films"
    assert "hasn't been set up" in body["error"]


def test_next_film_reports_all_rated_when_films_exist(app, client):
    register(client, "u@example.com", "pw")
    seed_film(app)
    client.post("/api/films/f1/ratings", json={"scores": {"originality": 3, "use_of_archive_materials": 3}})
    r = client.get("/api/films/next")
    assert r.status_code == 404
    assert r.get_json()["code"] == "all_rated"


# ---- sync status ------------------------------------------------------------

def test_sync_status_requires_admin(app, client):
    assert client.get("/api/admin/sync/status").status_code == 401
    register(client, "u@example.com", "pw")
    assert client.get("/api/admin/sync/status").status_code == 403


def test_status_idle_before_any_sync(app, client):
    make_admin(app, client)
    s = client.get("/api/admin/sync/status").get_json()
    assert s["state"] == "idle" and s["film_count"] == 0


def test_sync_reports_progress_and_blocks_second_start(app, client, monkeypatch):
    make_admin(app, client)
    release = threading.Event()
    reached = threading.Event()

    def slow_sync(self, films_repo, progress=None, **kw):
        progress("listing", 100, None)
        progress("descriptions", 3, 10)
        reached.set()
        assert release.wait(10)
        return 10

    monkeypatch.setattr(app.services["ia"].__class__, "sync_collection", slow_sync)

    assert client.post("/api/admin/sync").status_code == 202
    assert reached.wait(10)

    s = client.get("/api/admin/sync/status").get_json()
    assert (s["state"], s["phase"], s["done"], s["total"]) == ("running", "descriptions", 3, 10)

    again = client.post("/api/admin/sync")
    assert again.status_code == 409
    assert again.get_json()["status"]["state"] == "running"

    release.set()
    app.services["sync"].wait(10)
    s = client.get("/api/admin/sync/status").get_json()
    assert s["state"] == "done" and s["synced"] == 10 and s["finished_at"] >= s["started_at"]


def test_sync_failure_is_reported(app, client, monkeypatch):
    make_admin(app, client)

    def failing(self, films_repo, progress=None, **kw):
        raise RuntimeError("archive.org unreachable")

    monkeypatch.setattr(app.services["ia"].__class__, "sync_collection", failing)
    assert client.post("/api/admin/sync").status_code == 202
    app.services["sync"].wait(10)
    s = client.get("/api/admin/sync/status").get_json()
    assert s["state"] == "error" and "unreachable" in s["error"]
    # A failed sync doesn't wedge the service: a new one can start.
    monkeypatch.setattr(app.services["ia"].__class__, "sync_collection", lambda self, f, progress=None, **k: 0)
    assert client.post("/api/admin/sync").status_code == 202
    app.services["sync"].wait(10)
    assert client.get("/api/admin/sync/status").get_json()["state"] == "done"


def test_ia_sync_collection_emits_progress(app, monkeypatch):
    ia = app.services["ia"]
    docs = [{"identifier": f"x{i}", "title": "t"} for i in range(3)]
    monkeypatch.setattr(type(ia), "iter_collection_movies", lambda self, rows=100: iter(docs))

    async def fake(self, identifiers, workers, report=None):
        for i, _ in enumerate(identifiers, 1):
            report("descriptions", i, len(identifiers))
        return {}

    monkeypatch.setattr(type(ia), "_fetch_all_descriptions", fake)
    events = []
    n = ia.sync_collection(app.repos["films"], progress=lambda *a: events.append(a))
    assert n == 3
    assert events[0] == ("listing", 0, None)
    assert events[-1] == ("descriptions", 3, 3)


# ---- empty database ---------------------------------------------------------

def test_empty_requires_admin_and_confirmation(app, client):
    assert client.post("/api/admin/db/empty", json={"confirm": "EMPTY"}).status_code == 401
    register(client, "u@example.com", "pw")
    assert client.post("/api/admin/db/empty", json={"confirm": "EMPTY"}).status_code == 403

    logout(client)
    make_admin(app, client)
    seed_film(app)
    assert client.post("/api/admin/db/empty").status_code == 400
    assert client.post("/api/admin/db/empty", json={"confirm": "yes"}).status_code == 400
    assert app.repos["films"].count() == 1  # nothing deleted


def test_empty_deletes_films_and_ratings_but_keeps_users_and_criteria(app, client):
    make_admin(app, client)
    seed_film(app, "f1")
    seed_film(app, "f2")
    client.post("/api/films/f1/ratings", json={"scores": {"originality": 4, "use_of_archive_materials": 2}})
    users_before = len(app.db.fetchall("SELECT id FROM users"))
    criteria_before = len(app.db.fetchall("SELECT id FROM criteria"))

    r = client.post("/api/admin/db/empty", json={"confirm": "EMPTY"})
    assert r.status_code == 200
    d = r.get_json()["deleted"]
    assert d == {"rating_scores": 2, "ratings": 1, "film_notes": 0, "films": 2}

    for table in ("films", "ratings", "rating_scores"):
        assert app.db.fetchone(f"SELECT COUNT(1) AS n FROM {table}")["n"] == 0
    assert len(app.db.fetchall("SELECT id FROM users")) == users_before
    assert len(app.db.fetchall("SELECT id FROM criteria")) == criteria_before
    assert client.get("/api/me").status_code == 200  # admin is still logged in

    # ...and the user now sees the "not set up" message again.
    assert client.get("/api/films/next").get_json()["code"] == "no_films"
    # New films start from id 1 again.
    seed_film(app, "g1")
    assert app.repos["films"].get_by_identifier("g1")["id"] == 1


def test_empty_refused_while_sync_running(app, client, monkeypatch):
    make_admin(app, client)
    seed_film(app)
    release = threading.Event()
    started = threading.Event()

    def slow(self, films_repo, progress=None, **kw):
        started.set()
        release.wait(10)
        return 0

    monkeypatch.setattr(app.services["ia"].__class__, "sync_collection", slow)
    client.post("/api/admin/sync")
    assert started.wait(10)
    assert client.post("/api/admin/db/empty", json={"confirm": "EMPTY"}).status_code == 409
    assert app.repos["films"].count() == 1
    release.set()
    app.services["sync"].wait(10)


def test_search_uses_stable_sort_and_sync_dedupes(app, monkeypatch):
    """Regression: unsorted IA paging returned duplicate rows and dropped films."""
    from server.services import ia_service

    seen = {}

    class R:
        def raise_for_status(self): pass
        def json(self): return {"response": {"docs": [], "numFound": 0}}

    def fake_get(url, params=None, timeout=None):
        seen.update(params)
        return R()

    monkeypatch.setattr(ia_service.requests, "get", fake_get)
    app.services["ia"]._advancedsearch(page=1, rows=100)
    assert seen["sort[]"] == "identifier asc"

    ia = app.services["ia"]
    dup_docs = [{"identifier": "a", "title": "A"}, {"identifier": "a", "title": "A"}, {"identifier": "b", "title": "B"}]
    monkeypatch.setattr(type(ia), "iter_collection_movies", lambda self, rows=100: iter(dup_docs))

    async def none(self, identifiers, workers, report=None):
        return {}

    monkeypatch.setattr(type(ia), "_fetch_all_descriptions", none)
    assert ia.sync_collection(app.repos["films"]) == 2
