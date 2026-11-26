import csv
import io
import json

from server.tests.helpers import all_scores, assign, make_user, seed_film


def test_admin_routes_require_an_admin(app, client):
    paths = [("get", "/api/admin/jobs/status"), ("post", "/api/admin/db/empty"), ("get", "/api/admin/ratings.csv"),
             ("get", "/api/admin/db/tables"), ("get", "/api/admin/db/backup")]
    for method, path in paths:
        assert getattr(client, method)(path).status_code == 401, path
    rev, _ = make_user(app, "r@example.com", ["reviewer", "judge"])
    for method, path in paths:
        assert getattr(rev, method)(path).status_code == 403, path


def test_removed_routes_are_gone(app):
    rules = {r.rule for r in app.url_map.iter_rules()}
    for path in ["/api/admin/sync", "/api/admin/sync/status", "/api/admin/settings", "/api/admin/settings/collection",
                 "/api/admin/criteria", "/api/admin/criteria/<int:cid>", "/api/admin/notes.csv", "/api/criteria",
                 "/api/config", "/api/auth/login", "/api/auth/register", "/api/auth/github/login",
                 "/api/auth/github/callback", "/api/films/<identifier>/notes"]:
        assert path not in rules, path


def test_job_status_is_idle_with_a_film_count(app):
    admin, _ = make_user(app, "a@example.com", ["admin"])
    s = admin.get("/api/admin/jobs/status").get_json()
    assert s["state"] == "idle" and s["film_count"] == 0 and s["kind"] is None
    seed_film(app, "f1")
    assert admin.get("/api/admin/jobs/status").get_json()["film_count"] == 1


def test_startup_does_not_import_or_fetch_anything(app):
    assert app.repos["films"].count() == 0


def test_empty_requires_confirmation(app):
    admin, _ = make_user(app, "a@example.com", ["admin"])
    assert admin.post("/api/admin/db/empty", json={}).status_code == 400
    assert admin.post("/api/admin/db/empty", json={"confirm": "yes"}).status_code == 400


def test_empty_deletes_films_assignments_and_ratings_but_keeps_users(app):
    admin, aid = make_user(app, "a@example.com", ["admin"])
    rev, rid = make_user(app, "r@example.com", ["reviewer"])
    fid = seed_film(app, "f1")
    assign(app, rid, fid)
    rev.post("/api/films/f1/ratings", json={"scores": all_scores(), "comment": "hi"})
    r = admin.post("/api/admin/db/empty", json={"confirm": "EMPTY"})
    assert r.status_code == 200
    assert r.get_json()["deleted"] == {"rating_scores": 3, "ratings": 1, "assignments": 1, "films": 1}
    for t in ("films", "assignments", "ratings", "rating_scores"):
        assert app.db.fetchone(f"SELECT COUNT(*) AS n FROM {t}")["n"] == 0
    assert app.db.fetchone("SELECT COUNT(*) AS n FROM users")["n"] == 2
    assert seed_film(app, "again") == 1                        # ids restart


def test_empty_refused_while_a_job_runs(app, monkeypatch):
    import threading
    admin, _ = make_user(app, "a@example.com", ["admin"])
    release, started = threading.Event(), threading.Event()

    def job(progress):
        started.set()
        release.wait(10)
        return 0

    assert app.services["jobs"].start_job("titles", job)
    assert started.wait(10)
    assert admin.post("/api/admin/db/empty", json={"confirm": "EMPTY"}).status_code == 409
    release.set()
    app.services["jobs"].wait(10)


def test_db_browser_lists_tables_but_hides_internal_ones(app):
    admin, _ = make_user(app, "a@example.com", ["admin"])
    tables = admin.get("/api/admin/db/tables").get_json()
    assert set(tables) == {"schema_migrations", "users", "films", "assignments", "ratings", "rating_scores"}
    assert admin.get("/api/admin/db/login_links").status_code == 404
    assert admin.get("/api/admin/db/user_sessions").status_code == 404
    films = admin.get("/api/admin/db/films").get_json()
    assert films == []
    seed_film(app, "f1")
    assert admin.get("/api/admin/db/films").get_json()[0]["rating_count"] == 0


def test_ratings_csv_has_scores_totals_and_comments(app):
    admin, _ = make_user(app, "a@example.com", ["admin"])
    rev, rid = make_user(app, "r@example.com", ["reviewer"])
    fid = seed_film(app, "f1", "Film One")
    assign(app, rid, fid)
    rev.post("/api/films/f1/ratings", json={"scores": {"aesthetic": 10, "sound": 5, "appeal": 1}, "comment": "Nice, \"quoted\"\nline"})
    r = admin.get("/api/admin/ratings.csv")
    assert r.mimetype == "text/csv"
    rows = list(csv.reader(io.StringIO(r.get_data(as_text=True))))
    assert rows[0] == ["created_at", "user_email", "identifier", "title", "aesthetic", "sound", "appeal", "total", "comment"]
    assert rows[1][1:] == ["r@example.com", "f1", "Film One", "10", "5", "1", "16", "Nice, \"quoted\"\nline"]
    assert len(rows) == 2


def test_backup_and_restore_round_trip(app):
    admin, aid = make_user(app, "a@example.com", ["admin"])
    rev, rid = make_user(app, "r@example.com", ["reviewer"])
    fid = seed_film(app, "f1", creator="Sam", public_domain_works="Nosferatu")
    assign(app, rid, fid)
    rev.post("/api/films/f1/ratings", json={"scores": all_scores(), "comment": "hi"})
    backup = json.loads(admin.get("/api/admin/db/backup").data)
    assert backup["format_version"] == 2 and backup["schema_version"] == 1
    assert set(backup["tables"]) == {"schema_migrations", "users", "films", "assignments", "ratings", "rating_scores"}
    assert "password_hash" in backup["tables"]["users"][0]       # (existing behaviour: column exists, always empty now)

    admin.post("/api/admin/db/empty", json={"confirm": "EMPTY"})
    r = admin.post("/api/admin/db/restore", json=backup)
    assert r.status_code == 200 and r.get_json()["restored"]["films"] == 1
    assert app.repos["films"].get_by_identifier("f1")["creator"] == "Sam"
    assert app.repos["ratings"].get_for_user_film(rid, fid)["comment"] == "hi"
    assert app.repos["assignments"].get(rid, fid)["status"] == "rated"


def test_restore_rejects_old_or_foreign_backups(app):
    admin, _ = make_user(app, "a@example.com", ["admin"])
    good = json.loads(admin.get("/api/admin/db/backup").data)
    old = admin.post("/api/admin/db/restore", json={**good, "format_version": 1})                      # the old app's format
    assert old.status_code == 400 and "old version of the app" in old.get_json()["error"]
    assert admin.post("/api/admin/db/restore", json={**good, "format_version": 7}).get_json()["error"].startswith("Unsupported format_version")
    assert admin.post("/api/admin/db/restore", json={**good, "schema_version": 9}).status_code == 400
    assert admin.post("/api/admin/db/restore", json={**good, "app": "other"}).status_code == 400
    assert admin.post("/api/admin/db/restore", json={**good, "tables": []}).status_code == 400
    assert admin.post("/api/admin/db/restore", json={**good, "tables": {"users": [{"id": 1, "nope": 1}]}}).status_code == 400
    assert app.db.fetchone("SELECT COUNT(*) AS n FROM users")["n"] == 1


def test_restoring_a_backup_without_dependent_tables_clears_stale_rows(app):
    admin, aid = make_user(app, "a@example.com", ["admin"])
    rev, rid = make_user(app, "r@example.com", ["reviewer"])
    assign(app, rid, seed_film(app, "f1"))
    backup = json.loads(admin.get("/api/admin/db/backup").data)
    del backup["tables"]["assignments"]                            # e.g. a hand-trimmed file
    assert admin.post("/api/admin/db/restore", json=backup).status_code == 200
    assert app.db.fetchone("SELECT COUNT(*) AS n FROM assignments")["n"] == 0
