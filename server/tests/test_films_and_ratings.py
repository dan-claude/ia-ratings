from server.tests.helpers import register

def _insert_film(app, identifier="film1", title="Film 1"):
    conn = app.db.connect()
    try:
        conn.execute(
            "INSERT INTO films (ia_identifier, title, collection, mediatype, metadata_json, updated_at) "
            "VALUES (?, ?, ?, ?, NULL, datetime('now'))",
            (identifier, title, app.settings.collection, "movies"),
        )
        conn.commit()
    finally:
        conn.close()


def _clear_films(app):
    """Remove any seeded films so tests can control selection deterministically."""
    conn = app.db.connect()
    try:
        conn.execute("DELETE FROM films")
        conn.commit()
    finally:
        conn.close()

def test_next_film_requires_auth(client):
    assert client.get("/api/films/next").status_code == 401

def test_next_film_and_rate_then_exhaust(app, client):
    _clear_films(app)
    register(client, "e@example.com", "pw")
    _insert_film(app, "film1", "Film 1")

    r = client.get("/api/films/next")
    assert r.status_code == 200
    assert r.get_json()["identifier"] == "film1"

    crit = client.get("/api/criteria").get_json()
    scores = {c["key"]: c.get("max", 5) for c in crit}

    rr = client.post("/api/films/film1/ratings", json={"scores": scores})
    assert rr.status_code == 200

    assert client.get("/api/films/next").status_code == 404
