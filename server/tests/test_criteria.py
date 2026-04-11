from server.tests.helpers import register

def test_criteria_requires_auth(client):
    assert client.get("/api/criteria").status_code == 401

def test_criteria_returns_seeded_criteria(client):
    register(client, "d@example.com", "pw")
    r = client.get("/api/criteria")
    assert r.status_code == 200
    keys = [c["key"] for c in r.get_json()]
    assert "originality" in keys
    assert "use_of_archive_materials" in keys
