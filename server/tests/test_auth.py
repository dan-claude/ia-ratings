from server.tests.helpers import register, login, logout

def test_register_sets_session_and_me_works(client):
    r = register(client, "a@example.com", "pw1")
    assert r.status_code == 200
    me = client.get("/api/me")
    assert me.status_code == 200
    assert me.get_json()["email"] == "a@example.com"

def test_login_logout_flow(client):
    register(client, "b@example.com", "pw2")
    logout(client)

    r = login(client, "b@example.com", "pw2")
    assert r.status_code == 200

    me = client.get("/api/me")
    assert me.status_code == 200
    assert me.get_json()["email"] == "b@example.com"

    logout(client)
    assert client.get("/api/me").status_code == 401

def test_login_rejects_bad_password(client):
    register(client, "c@example.com", "pw3")
    logout(client)
    assert login(client, "c@example.com", "wrong").status_code == 401
