"""Sign-in by magic link: invite, sign in, expiry, cancel, re-issue, rate limit, first-admin CLI."""
import importlib
import json

import pytest

from server.tests.helpers import make_user

SIGNIN = "/api/auth/signin"


def admin_client(app, email="admin@example.com"):
    return make_user(app, email, ["admin"])[0]


def token_of(res):
    return res.get_json()["link"]["token"]


def invite(admin, email="new@example.com", roles=("reviewer",), **extra):
    return admin.post("/api/admin/users", json={"email": email, "roles": list(roles), **extra})


def expire(app, token_hash_like=None, when="-1 day"):
    conn = app.db.connect()
    with conn:
        conn.execute("UPDATE login_links SET expires_at = datetime('now', ?)", (when,))
    conn.close()


# ---- inviting ------------------------------------------------------------------------

def test_invite_creates_the_user_with_roles_and_returns_a_link_once(app):
    admin = admin_client(app)
    r = invite(admin, " New@Example.com ", ["reviewer", "judge", "judge"])
    assert r.status_code == 201
    d = r.get_json()
    assert d["user"]["email"] == "new@example.com" and d["user"]["roles"] == ["reviewer", "judge"]
    assert d["link"]["path"] == f"/signin#{d['link']['token']}"
    assert d["link"]["expires_at"].endswith("Z")
    row = app.repos["users"].get_by_email("new@example.com")
    assert app.repos["users"].roles_of(row) == ["reviewer", "judge"]


def test_only_the_hash_of_the_link_is_stored(app):
    admin = admin_client(app)
    token = token_of(invite(admin))
    rows = app.db.fetchall("SELECT * FROM login_links")
    assert len(rows) == 1 and len(rows[0]["token_hash"]) == 64 and token not in rows[0]["token_hash"]
    assert token not in json.dumps([dict(r) for r in app.db.fetchall("SELECT * FROM login_links")])


def test_invite_validation(app):
    admin = admin_client(app)
    assert invite(admin, "nope").status_code == 400
    assert invite(admin, "a b@example.com").status_code == 400
    assert admin.post("/api/admin/users", json={"roles": []}).status_code == 400
    assert admin.post("/api/admin/users", json={"email": 5}).status_code == 400
    assert invite(admin, roles=["root"]).status_code == 400
    assert admin.post("/api/admin/users", json={"email": "a@b.co", "roles": "judge"}).status_code == 400
    assert invite(admin, expires_at="2001-01-01").status_code == 400          # in the past
    assert invite(admin, expires_at="soon").status_code == 400
    assert invite(admin, expires_at=7).status_code == 400
    assert app.db.fetchone("SELECT COUNT(*) AS n FROM users")["n"] == 1        # nothing was created
    assert invite(admin, "dup@example.com").status_code == 201
    assert invite(admin, "DUP@example.com").status_code == 409


def test_a_person_can_be_invited_with_no_roles(app):
    admin = admin_client(app)
    assert invite(admin, roles=[]).status_code == 201
    assert admin.post("/api/admin/users", json={"email": "x@example.com"}).status_code == 201


def test_invite_expiry_can_be_a_date_or_a_datetime(app):
    admin = admin_client(app)
    a = invite(admin, "a@example.com", expires_at="2999-05-06").get_json()["link"]["expires_at"]
    assert a == "2999-05-06T23:59:59Z"
    b = invite(admin, "b@example.com", expires_at="2999-05-06T10:00:00+02:00").get_json()["link"]["expires_at"]
    assert b == "2999-05-06T08:00:00Z"
    c = invite(admin, "c@example.com").get_json()["link"]["expires_at"]           # default: about 30 days
    assert c.startswith("20")


def test_invite_routes_require_an_admin(app, client):
    other, uid = make_user(app, "o@example.com", ["reviewer", "judge"])
    for c, code in ((client, 401), (other, 403)):
        assert c.post("/api/admin/users", json={"email": "a@b.co"}).status_code == code
        assert c.get("/api/admin/users").status_code == code
        assert c.post(f"/api/admin/users/{uid}/login-link").status_code == code
        assert c.put(f"/api/admin/users/{uid}/login-link", json={"expires_at": "2999-01-01"}).status_code == code
        assert c.delete(f"/api/admin/users/{uid}/login-link").status_code == code


# ---- signing in ----------------------------------------------------------------------

def test_a_link_signs_the_person_in(app, client):
    admin = admin_client(app)
    token = token_of(invite(admin, "new@example.com", ["reviewer"]))
    assert client.get("/api/me").status_code == 401
    r = client.post(SIGNIN, json={"token": token})
    assert r.status_code == 200 and r.get_json() == {"ok": True}
    me = client.get("/api/me").get_json()
    assert me["email"] == "new@example.com" and me["roles"] == ["reviewer"]


def test_a_link_can_be_used_again_and_again(app):
    admin = admin_client(app)
    token = token_of(invite(admin))
    for _ in range(3):
        c = app.test_client()
        assert c.post(SIGNIN, json={"token": token}).status_code == 200
        assert c.get("/api/me").status_code == 200
        c.post("/api/auth/logout")
        assert c.get("/api/me").status_code == 401


@pytest.mark.parametrize("body", [{}, {"token": ""}, {"token": 5}, {"token": None}, {"token": "nope"}, {"token": "x" * 500},
                                  {"token": ["a"]}, None])
def test_bad_tokens_are_refused_alike(app, client, body):
    admin_client(app)
    r = client.post(SIGNIN, json=body)
    assert r.status_code == 401 and "not valid" in r.get_json()["error"]
    assert client.get("/api/me").status_code == 401


def test_an_expired_link_is_refused_and_checked_on_every_use(app):
    admin = admin_client(app)
    token = token_of(invite(admin))
    c = app.test_client()
    assert c.post(SIGNIN, json={"token": token}).status_code == 200
    expire(app)
    assert app.test_client().post(SIGNIN, json={"token": token}).status_code == 401
    # the admin can move the expiry to revive it
    uid = app.repos["users"].get_by_email("new@example.com")["id"]
    assert admin.put(f"/api/admin/users/{uid}/login-link", json={"expires_at": "2999-01-01"}).status_code == 200
    assert app.test_client().post(SIGNIN, json={"token": token}).status_code == 200


def test_signing_in_replaces_an_existing_session(app):
    admin = admin_client(app)
    t1, t2 = token_of(invite(admin, "a@example.com")), token_of(invite(admin, "b@example.com"))
    c = app.test_client()
    c.post(SIGNIN, json={"token": t1})
    c.post(SIGNIN, json={"token": t2})
    assert c.get("/api/me").get_json()["email"] == "b@example.com"
    assert app.db.fetchone("SELECT COUNT(*) AS n FROM user_sessions WHERE user_id = (SELECT id FROM users WHERE email='a@example.com')")["n"] == 0


def test_the_get_on_the_link_does_not_sign_anyone_in(app, client):
    token = token_of(invite(admin_client(app)))
    client.get(f"/signin?x=1")          # opening the page (any GET) never logs in
    client.get("/api/auth/signin")
    assert client.get("/api/me").status_code == 401


# ---- cancel / re-issue / expiry ------------------------------------------------------

def test_a_new_link_cancels_the_old_one_and_ends_logins(app):
    admin = admin_client(app)
    old = token_of(invite(admin))
    person = app.test_client()
    person.post(SIGNIN, json={"token": old})
    uid = app.repos["users"].get_by_email("new@example.com")["id"]
    r = admin.post(f"/api/admin/users/{uid}/login-link", json={"expires_at": "2999-01-01"})
    assert r.status_code == 201 and r.get_json()["link"]["expires_at"] == "2999-01-01T23:59:59Z"
    new = token_of(r)
    assert new != old
    assert person.get("/api/me").status_code == 401                              # logged out
    assert app.test_client().post(SIGNIN, json={"token": old}).status_code == 401
    assert app.test_client().post(SIGNIN, json={"token": new}).status_code == 200
    assert app.db.fetchone("SELECT COUNT(*) AS n FROM login_links WHERE user_id=? AND revoked_at IS NULL", (uid,))["n"] == 1


def test_cancelling_a_link_ends_logins(app):
    admin = admin_client(app)
    token = token_of(invite(admin))
    person = app.test_client()
    person.post(SIGNIN, json={"token": token})
    uid = app.repos["users"].get_by_email("new@example.com")["id"]
    assert admin.delete(f"/api/admin/users/{uid}/login-link").status_code == 200
    assert person.get("/api/me").status_code == 401
    assert app.test_client().post(SIGNIN, json={"token": token}).status_code == 401
    assert admin.put(f"/api/admin/users/{uid}/login-link", json={"expires_at": "2999-01-01"}).status_code == 404   # nothing to change
    assert admin.delete(f"/api/admin/users/{uid}/login-link").status_code == 200                                   # harmless twice
    assert admin.post(f"/api/admin/users/{uid}/login-link").status_code == 201                                     # can issue again


def test_an_admin_acting_on_themselves_keeps_their_own_login(app):
    admin, aid = make_user(app, "a@example.com", ["admin"])
    other = app.test_client()
    with other.session_transaction() as s:           # a second login of the same admin
        s["user_id"] = aid
        s["sid"] = app.repos["sessions"].create(aid)
    assert admin.post(f"/api/admin/users/{aid}/login-link").status_code == 201
    assert admin.get("/api/me").status_code == 200
    assert other.get("/api/me").status_code == 401


def test_unknown_users_and_bad_expiry(app):
    admin = admin_client(app)
    assert admin.post("/api/admin/users/999/login-link").status_code == 404
    assert admin.delete("/api/admin/users/999/login-link").status_code == 404
    assert admin.put("/api/admin/users/999/login-link", json={"expires_at": "2999-01-01"}).status_code == 404
    uid = app.repos["users"].create_user("x@example.com")
    assert admin.post(f"/api/admin/users/{uid}/login-link", json={"expires_at": "2001-01-01"}).status_code == 400
    admin.post(f"/api/admin/users/{uid}/login-link")
    assert admin.put(f"/api/admin/users/{uid}/login-link", json={}).status_code == 400
    assert admin.put(f"/api/admin/users/{uid}/login-link", json={"expires_at": "2001-01-01"}).status_code == 400


def test_users_list_shows_roles_and_link_state(app):
    admin = admin_client(app)
    invite(admin, "a@example.com", ["reviewer"])
    invite(admin, "b@example.com", ["judge"])
    app.repos["users"].create_user("c@example.com")
    uid_b = app.repos["users"].get_by_email("b@example.com")["id"]
    expire(app)                                     # both links lapse
    admin.post(f"/api/admin/users/{uid_b}/login-link", json={"expires_at": "2999-01-01"})
    rows = {u["email"]: u for u in admin.get("/api/admin/users").get_json()}
    assert rows["admin@example.com"]["link"] is None and rows["c@example.com"]["link"] is None
    assert rows["a@example.com"]["link"]["state"] == "expired"
    assert rows["b@example.com"]["link"] == {"state": "active", "expires_at": "2999-01-01T23:59:59Z"}
    assert rows["a@example.com"]["roles"] == ["reviewer"] and rows["b@example.com"]["is_judge"] is True
    assert "token" not in json.dumps(rows) and "password_hash" not in json.dumps(rows)


# ---- rate limit, body limit ----------------------------------------------------------

def _build(monkeypatch, tmp_path, hops=None):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "s.db"))
    monkeypatch.setenv("SESSION_SECRET", "s")
    if hops is None:
        monkeypatch.delenv("TRUSTED_PROXY_HOPS", raising=False)
    else:
        monkeypatch.setenv("TRUSTED_PROXY_HOPS", hops)
    import server.app as m
    importlib.reload(m)
    app = m.create_app()
    app.config.update(TESTING=True)
    return app


def _attempts(app, n, forwarded=lambda i: f"203.0.113.{i}"):
    codes = []
    for i in range(n):
        r = app.test_client().post(
            SIGNIN, json={"token": "wrong"}, environ_base={"REMOTE_ADDR": "10.1.1.1"},
            headers={"X-Forwarded-For": forwarded(i)},
        )
        codes.append(r.status_code)
    return codes


def test_behind_a_trusted_proxy_each_client_has_its_own_rate_limit(monkeypatch, tmp_path):
    app = _build(monkeypatch, tmp_path, "1")
    assert 429 not in _attempts(app, 15)               # 15 different real clients, none limited


def test_without_a_trusted_proxy_a_spoofed_header_does_not_help(monkeypatch, tmp_path):
    app = _build(monkeypatch, tmp_path)
    assert _attempts(app, 12).count(429) == 2          # header ignored: same address, 10 per minute


def test_one_client_is_still_limited_behind_the_proxy(monkeypatch, tmp_path):
    app = _build(monkeypatch, tmp_path, "1")
    assert _attempts(app, 12, forwarded=lambda i: "203.0.113.9").count(429) == 2


def test_oversized_body_is_rejected_even_before_sign_in(client):
    r = client.post(SIGNIN, json={"token": "p" * (2 * 1024 * 1024)})
    assert r.status_code == 413 and r.get_json()["error"]


# ---- first admin from the command line -----------------------------------------------

def run_cli(monkeypatch, capsys, db, *args, public_url=None):
    from tools import print_db
    monkeypatch.setenv("SESSION_SECRET", "s")
    if public_url is None:
        monkeypatch.delenv("PUBLIC_URL", raising=False)
    else:
        monkeypatch.setenv("PUBLIC_URL", public_url)
    code = print_db.main(["--db", str(db), *args])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_cli_invite_creates_the_first_admin_and_prints_a_working_link(app, client, tmp_path, monkeypatch, capsys):
    code, out, _ = run_cli(monkeypatch, capsys, app.config["DB_PATH"], "--invite", "Boss@Example.com", "--admin",
                           public_url="https://rate.example.org/")
    assert code == 0
    assert "Created boss@example.com" in out and "roles: admin" in out
    link = next(ln for ln in out.splitlines() if ln.startswith("https://rate.example.org/signin#"))
    token = link.split("#", 1)[1]
    assert client.post(SIGNIN, json={"token": token}).status_code == 200
    me = client.get("/api/me").get_json()
    assert me["email"] == "boss@example.com" and me["is_admin"] is True
    assert client.get("/api/admin/users").status_code == 200


def test_cli_invite_on_an_existing_user_adds_roles_and_replaces_the_link(app, tmp_path, monkeypatch, capsys):
    db = app.config["DB_PATH"]
    admin = admin_client(app, "a@example.com")
    old = token_of(invite(admin, "x@example.com", ["reviewer"]))
    code, out, _ = run_cli(monkeypatch, capsys, db, "--invite", "x@example.com", "--roles", "judge", "--days", "3")
    assert code == 0 and "Updated x@example.com" in out and "roles: reviewer, judge" in out
    assert "Set PUBLIC_URL" in out and "/signin#" in out
    assert app.test_client().post(SIGNIN, json={"token": old}).status_code == 401      # old link cancelled


def test_cli_invite_errors(app, tmp_path, monkeypatch, capsys):
    db = app.config["DB_PATH"]
    for args in (["--invite", "nope"], ["--invite", "a@example.com", "--roles", "root"], ["--invite", "a@example.com", "--days", "0"]):
        code, _, err = run_cli(monkeypatch, capsys, db, *args)
        assert code == 2 and err.startswith("Error:")
    assert app.db.fetchone("SELECT COUNT(*) AS n FROM users")["n"] == 0


def test_cli_invite_creates_a_fresh_database_if_missing(tmp_path, monkeypatch, capsys):
    db = tmp_path / "new.db"
    code, out, _ = run_cli(monkeypatch, capsys, db, "--invite", "a@example.com", "--admin")
    assert code == 0 and db.exists() and "roles: admin" in out


def test_the_signin_page_is_served_by_the_app_not_a_404(client):
    # With the client built this is index.html (200); without a build it is the 500 "Client not built" JSON.
    assert client.get("/signin").status_code in (200, 500)
