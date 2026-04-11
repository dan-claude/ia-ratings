from server.tests.helpers import register


def test_admin_requires_admin_user(app, client):
    # Not logged in
    r = client.post("/api/admin/sync")
    assert r.status_code == 401

    # Logged in but not admin
    register(client, "u@example.com", "pw")
    r2 = client.post("/api/admin/sync")
    assert r2.status_code == 403


def test_admin_sync_inserts_films(monkeypatch, app, client):
    fake_docs = [
        {"identifier": "ia_film_1", "title": "IA Film 1", "description": "A test description"},
        {"identifier": "ia_film_2", "title": "IA Film 2"},
    ]

    def fake_iter(self, rows=100):
        for d in fake_docs:
            yield d

    monkeypatch.setattr(app.services["ia"].__class__, "iter_collection_movies", fake_iter)

    # create + login user
    register(client, "admin@example.com", "pw")
    u = app.repos["users"].get_by_email("admin@example.com")
    app.repos["users"].set_admin(int(u["id"]), True)

    r = client.post("/api/admin/sync")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body.get("added", body.get("synced")) >= 2

    # Ensure description stored
    row = app.repos["films"].get_by_identifier("ia_film_1")
    assert row is not None
    assert ("description" in row.keys())
    assert row["description"] == "A test description"


    nf = client.get("/api/films/next")
    assert nf.status_code == 200
    assert nf.get_json()["identifier"] in ("ia_film_1", "ia_film_2")
