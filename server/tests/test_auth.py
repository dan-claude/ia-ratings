"""Sessions and /api/me. (How people get in is by magic link; see test_login_links.py once it exists.)"""
from server.tests.helpers import login_as, make_user


def test_not_logged_in_is_401(client):
    assert client.get("/api/me").status_code == 401


def test_me_reports_the_user_and_roles(app):
    c, uid = make_user(app, "a@example.com", ["reviewer", "judge"])
    me = c.get("/api/me").get_json()
    assert me["id"] == uid and me["email"] == "a@example.com"
    assert (me["is_admin"], me["is_reviewer"], me["is_judge"]) == (False, True, True)
    assert me["roles"] == ["reviewer", "judge"]


def test_logout_ends_the_session(app):
    c, _ = make_user(app)
    assert c.get("/api/me").status_code == 200
    assert c.post("/api/auth/logout").status_code == 200
    assert c.get("/api/me").status_code == 401


def test_login_helper_gives_independent_sessions(app):
    _, uid = make_user(app, "a@example.com")
    a, b = login_as(app, uid), login_as(app, uid)
    a.post("/api/auth/logout")
    assert a.get("/api/me").status_code == 401
    assert b.get("/api/me").status_code == 200
