"""Security hardening: startup secret, proxy-aware rate limit, body limits, canonical
archive.org identity, server-side sessions, CSV neutralising, author display names."""
import csv
import importlib
import io
import json

import pytest

import server.services.auth_service as auth_mod
from server.config import _DEV_SECRET, Settings
from server.tests.helpers import register, login


def build_app(monkeypatch, tmp_path, **env):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "s.db"))
    monkeypatch.setenv("AUTH_SCHEME", env.pop("AUTH_SCHEME", "local"))
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    import server.app as app_module
    importlib.reload(app_module)
    return app_module


def make_user(app, email, roles=()):
    c = app.test_client()
    register(c, email, "pw")
    uid = int(app.repos["users"].get_by_email(email)["id"])
    app.repos["users"].set_roles(uid, list(roles))
    return c, uid


# ---- SESSION_SECRET ---------------------------------------------------------------

def test_server_refuses_to_start_without_a_session_secret(monkeypatch, tmp_path):
    m = build_app(monkeypatch, tmp_path, SESSION_SECRET=None)
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        m.create_app()


def test_server_refuses_the_public_default_secret(monkeypatch, tmp_path):
    m = build_app(monkeypatch, tmp_path, SESSION_SECRET=_DEV_SECRET)
    with pytest.raises(RuntimeError):
        m.create_app()


def test_dev_mode_uses_a_random_secret_and_plain_http_cookies(monkeypatch, tmp_path):
    m = build_app(monkeypatch, tmp_path, SESSION_SECRET=None)
    a1, a2 = m.create_app(dev=True), m.create_app(dev=True)
    assert a1.secret_key != _DEV_SECRET and a1.secret_key != a2.secret_key
    assert a1.config["SESSION_COOKIE_SECURE"] is False


def test_production_cookies_are_secure(app):
    assert app.config["SESSION_COOKIE_SECURE"] is True


def test_dev_entrypoint_binds_to_localhost_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("FLASK_RUN_HOST", raising=False)
    m = build_app(monkeypatch, tmp_path, SESSION_SECRET="s")
    seen = {}
    monkeypatch.setattr(m.Flask, "run", lambda self, **kw: seen.update(kw))
    monkeypatch.setattr(m, "_pick_available_port", lambda h, p: p)
    assert m.main([]) == 0
    assert seen["host"] == "127.0.0.1"


def test_debugger_refused_on_non_local_address(monkeypatch, tmp_path):
    m = build_app(monkeypatch, tmp_path, SESSION_SECRET="s")
    monkeypatch.setattr(m, "_pick_available_port", lambda h, p: p)
    with pytest.raises(SystemExit, match="debugger"):
        m.main(["--host", "0.0.0.0", "--debug"])


# ---- proxy-aware rate limit --------------------------------------------------------

def _logins(app, n):
    codes = []
    for i in range(n):
        r = app.test_client().post(
            "/api/auth/login", json={"email": "nobody@example.com", "password": "x"},
            environ_base={"REMOTE_ADDR": "10.1.1.1"},
            headers={"X-Forwarded-For": f"203.0.113.{i}"},
        )
        codes.append(r.status_code)
    return codes


def test_behind_a_trusted_proxy_each_client_has_its_own_rate_limit(monkeypatch, tmp_path):
    m = build_app(monkeypatch, tmp_path, SESSION_SECRET="s", TRUSTED_PROXY_HOPS="1")
    assert 429 not in _logins(m.create_app(), 15)   # 15 different real clients, none limited


def test_without_a_trusted_proxy_a_spoofed_header_does_not_help(monkeypatch, tmp_path):
    m = build_app(monkeypatch, tmp_path, SESSION_SECRET="s")  # TRUSTED_PROXY_HOPS unset = 0
    assert _logins(m.create_app(), 12).count(429) == 2     # header ignored: same address


def test_one_client_is_still_limited_behind_the_proxy(monkeypatch, tmp_path):
    m = build_app(monkeypatch, tmp_path, SESSION_SECRET="s", TRUSTED_PROXY_HOPS="1")
    app = m.create_app()
    codes = [app.test_client().post(
        "/api/auth/login", json={"email": "x@example.com", "password": "x"},
        environ_base={"REMOTE_ADDR": "10.1.1.1"}, headers={"X-Forwarded-For": "203.0.113.9"},
    ).status_code for _ in range(12)]
    assert codes.count(429) == 2


def test_proxy_hops_setting_parsing(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "2")
    assert Settings().trusted_proxy_hops == 2
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "garbage")
    assert Settings().trusted_proxy_hops == 0
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "-3")
    assert Settings().trusted_proxy_hops == 0


# ---- request body limits -----------------------------------------------------------

def test_oversized_body_is_rejected_even_before_login(client):
    r = client.post("/api/auth/login", json={"email": "a@b.co", "password": "p" * (2 * 1024 * 1024)})
    assert r.status_code == 413 and r.get_json()["error"]


def test_normal_requests_are_unaffected_by_the_limit(client):
    assert register(client).status_code == 200


def test_admin_import_accepts_a_large_csv_body(app):
    admin, _ = make_user(app, "a@example.com", ["admin"])
    big = "link\n" + "\n".join(f"https://archive.org/details/film{i}" for i in range(50000))  # ~1.9 MB
    assert 1024 * 1024 < len(big.encode()) <= 2 * 1024 * 1024
    r = admin.post("/api/admin/import/preview", json={"csv_text": big})
    assert r.status_code == 400 and "Too many rows" in r.get_json()["error"]   # parsed (5000-row cap), not 413
    ok = "link\n" + "\n".join(f"https://archive.org/details/film{i}" for i in range(4500))
    assert admin.post("/api/admin/import/preview", json={"csv_text": ok}).status_code == 200


def test_admin_restore_accepts_a_large_backup_but_other_admin_routes_do_not(app):
    admin, _ = make_user(app, "a@example.com", ["admin"])
    backup = json.loads(admin.get("/api/admin/db/backup").data)
    backup["tables"]["films"] = [
        {"id": i + 1, "ia_identifier": f"f{i}", "title": "T" * 100, "collection": "c"} for i in range(12000)
    ]  # a couple of MB of JSON
    assert len(json.dumps(backup)) > 1024 * 1024
    assert admin.post("/api/admin/db/restore", json=backup).status_code == 200
    assert admin.put("/api/admin/settings/collection", json={"collection": "x" * (2 * 1024 * 1024)}).status_code == 413


# ---- canonical archive.org identity ------------------------------------------------

class FakeIA:
    def __init__(self, values=None, ok=True):
        self.values, self.ok = values, ok

    def json(self):
        d = {"success": self.ok}
        if self.values is not None:
            d["values"] = self.values
        return d


@pytest.fixture()
def ia_app(monkeypatch, tmp_path):
    m = build_app(monkeypatch, tmp_path, SESSION_SECRET="s", AUTH_SCHEME="ia")
    app = m.create_app()
    app.config.update(TESTING=True)
    return app


def ia_login(app, typed, response):
    monkeypatch_post = auth_mod._requests
    orig = monkeypatch_post.post
    monkeypatch_post.post = lambda *a, **k: response
    try:
        c = app.test_client()
        r = c.post("/api/auth/login", json={"username": typed, "password": "pw"})
        from server.routes.auth import limiter
        limiter.reset()
        return c, r
    finally:
        monkeypatch_post.post = orig


def user_id(c):
    return c.get("/api/me").get_json()["id"]


def test_every_way_of_typing_the_same_ia_account_is_one_user(ia_app):
    vals = {"screenname": "Alice"}
    ids = set()
    for typed in ("Alice", "alice", " ALICE ", "alice@example.com"):
        c, r = ia_login(ia_app, typed, FakeIA(vals))
        assert r.status_code == 200, typed
        ids.add(user_id(c))
    assert len(ids) == 1
    row = ia_app.db.fetchone("SELECT ia_username, email FROM users")
    assert row["ia_username"] == "alice" and row["email"] == "alice@users.archive.org"


def test_itemname_is_preferred_and_at_sign_stripped(ia_app):
    c, _ = ia_login(ia_app, "whatever", FakeIA({"itemname": "@Bob_Smith", "screenname": "Robert S."}))
    assert ia_app.db.fetchone("SELECT ia_username FROM users")["ia_username"] == "bob_smith"


def test_different_ia_accounts_stay_different(ia_app):
    a, _ = ia_login(ia_app, "a", FakeIA({"screenname": "alice"}))
    b, _ = ia_login(ia_app, "b", FakeIA({"screenname": "bob"}))
    assert user_id(a) != user_id(b)


def test_email_login_without_a_name_in_the_response_is_refused(ia_app):
    c, r = ia_login(ia_app, "alice@example.com", FakeIA({}))
    assert r.status_code == 401 and "username" in r.get_json()["error"]
    assert ia_app.db.fetchone("SELECT COUNT(*) AS n FROM users")["n"] == 0


def test_username_login_still_works_if_the_response_has_no_name(ia_app):
    c, r = ia_login(ia_app, "Carol", FakeIA(None))
    assert r.status_code == 200
    assert ia_app.db.fetchone("SELECT ia_username FROM users")["ia_username"] == "carol"


def test_failed_ia_login_is_rejected(ia_app):
    c, r = ia_login(ia_app, "alice", FakeIA({"reason": "account_bad_password"}, ok=False))
    assert r.status_code == 401 and r.get_json()["error"] == "account_bad_password"


def test_weird_ia_response_shapes_do_not_crash(ia_app):
    for resp in (type("R", (), {"json": lambda self: []})(), type("R", (), {"json": lambda self: {"success": True, "values": "x"}})()):
        c, r = ia_login(ia_app, "dave", resp)
        assert r.status_code in (200, 401)


def test_legacy_account_keyed_on_typed_email_is_adopted(ia_app):
    old = ia_app.repos["users"].create_ia_user("alice@example.com")  # how older versions stored it
    c, r = ia_login(ia_app, "alice@example.com", FakeIA({"screenname": "Alice"}))
    assert user_id(c) == old                       # same account, ratings and roles kept
    assert ia_app.db.fetchone("SELECT ia_username FROM users WHERE id=?", (old,))["ia_username"] == "alice"
    c2, _ = ia_login(ia_app, "alice", FakeIA({"screenname": "Alice"}))
    assert user_id(c2) == old


def test_legacy_mixed_case_account_is_matched(ia_app):
    old = ia_app.repos["users"].create_ia_user("Alice")
    c, _ = ia_login(ia_app, "alice", FakeIA({"screenname": "alice"}))
    assert user_id(c) == old


def test_a_non_email_alias_does_not_adopt_someone_elses_legacy_account(ia_app):
    old = ia_app.repos["users"].create_ia_user("bob")
    c, _ = ia_login(ia_app, "bob", FakeIA({"screenname": "alice"}))   # typed "bob", archive.org says alice
    assert user_id(c) != old


# ---- author display name -----------------------------------------------------------

def test_note_author_never_exposes_an_email_address(app):
    app.repos["films"].upsert_many_from_ia([{"identifier": "f1", "title": "T"}])
    uid = app.repos["users"].create_ia_user("legacy@example.com")  # old row keyed on an email
    app.repos["users"].set_roles(uid, ["judge"])
    c = app.test_client()
    with c.session_transaction() as s:
        s["user_id"] = uid
        s["sid"] = app.repos["sessions"].create(uid)
    c.post("/api/films/f1/notes", json={"text": "hi"})
    assert c.get("/api/films/f1/notes").get_json()[0]["author"] == "legacy"


# ---- server-side sessions ----------------------------------------------------------

def test_logout_ends_the_session_even_for_a_copied_cookie(app):
    c = app.test_client()
    register(c)
    cookie = c.get_cookie("session").value
    assert c.get("/api/me").status_code == 200
    c.post("/api/auth/logout")
    thief = app.test_client()
    thief.set_cookie("session", cookie, domain="localhost")
    assert thief.get("/api/me").status_code == 401


def test_a_forged_cookie_without_a_server_session_is_rejected(app):
    from flask.sessions import SecureCookieSessionInterface
    admin, aid = make_user(app, "a@example.com", ["admin"])
    ser = SecureCookieSessionInterface().get_signing_serializer(app)
    for payload in ({"user_id": aid}, {"user_id": aid, "sid": "guess"}, {"user_id": aid, "sid": 5}):
        c = app.test_client()
        c.set_cookie("session", ser.dumps(payload), domain="localhost")
        assert c.get("/api/admin/db/tables").status_code == 401


def test_session_cookie_for_another_user_does_not_work(app):
    a, aid = make_user(app, "a@example.com", ["admin"])
    b, bid = make_user(app, "b@example.com")
    from flask.sessions import SecureCookieSessionInterface
    sid_b = app.repos["sessions"].create(bid)
    ser = SecureCookieSessionInterface().get_signing_serializer(app)
    c = app.test_client()
    c.set_cookie("session", ser.dumps({"user_id": aid, "sid": sid_b}), domain="localhost")  # b's sid, a's id
    assert c.get("/api/me").status_code == 401


def test_sessions_expire_after_eight_hours(app):
    c = app.test_client()
    register(c)
    assert c.get("/api/me").status_code == 200
    conn = app.db.connect()
    with conn:
        conn.execute("UPDATE user_sessions SET created_at = datetime('now', '-9 hours')")
    conn.close()
    assert c.get("/api/me").status_code == 401


def test_logging_in_again_replaces_the_old_session(app):
    c = app.test_client()
    register(c, "u@example.com")
    c.post("/api/auth/logout")
    login(c, "u@example.com")
    login(c, "u@example.com")
    assert app.db.fetchone("SELECT COUNT(*) AS n FROM user_sessions")["n"] == 1


def test_sessions_are_hashed_and_hidden_from_admin_views(app):
    admin, aid = make_user(app, "a@example.com", ["admin"])
    sid = admin.get_cookie("session")
    stored = app.db.fetchone("SELECT sid_hash FROM user_sessions")["sid_hash"]
    assert len(stored) == 64  # sha-256 hex, not the raw token
    assert "user_sessions" not in admin.get("/api/admin/db/tables").get_json()
    assert "user_sessions" not in json.loads(admin.get("/api/admin/db/backup").data)["tables"]
    assert admin.get("/api/admin/db/user_sessions").status_code == 404


def test_restore_revokes_other_sessions_but_keeps_the_admins_own(app):
    admin, aid = make_user(app, "a@example.com", ["admin"])
    other, oid = make_user(app, "o@example.com")
    backup = json.loads(admin.get("/api/admin/db/backup").data)
    assert other.get("/api/me").status_code == 200
    assert admin.post("/api/admin/db/restore", json=backup).status_code == 200
    assert other.get("/api/me").status_code == 401
    assert admin.get("/api/me").status_code == 200


def test_restore_that_removes_the_admins_account_logs_them_out(app):
    admin, aid = make_user(app, "a@example.com", ["admin"])
    backup = json.loads(admin.get("/api/admin/db/backup").data)
    backup["tables"]["users"][0]["email"] = "someone.else@example.com"   # id now belongs to another person
    assert admin.post("/api/admin/db/restore", json=backup).status_code == 200
    assert admin.get("/api/me").status_code == 401


def test_failed_restore_keeps_sessions(app):
    admin, aid = make_user(app, "a@example.com", ["admin"])
    other, _ = make_user(app, "o@example.com")
    bad = {"app": "ia_ratings", "format_version": 1, "tables": {"users": [{"id": 1, "nope": 1}]}}
    assert admin.post("/api/admin/db/restore", json=bad).status_code == 400
    assert other.get("/api/me").status_code == 200


def test_migration_v9_upgrades_an_old_database(tmp_path):
    import sqlite3
    from server.db import Database
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.executescript("""CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT (datetime('now')));""")
    conn.commit(); conn.close()
    db = Database(path)
    assert db.fetchone("SELECT COUNT(*) AS n FROM user_sessions")["n"] == 0
    assert db.fetchone("SELECT 1 AS ok FROM schema_migrations WHERE version = 9")["ok"] == 1
    Database(path)  # idempotent


def test_old_cookies_without_a_session_id_are_logged_out_after_upgrade(app):
    from flask.sessions import SecureCookieSessionInterface
    _, uid = make_user(app, "u@example.com")
    ser = SecureCookieSessionInterface().get_signing_serializer(app)
    c = app.test_client()
    c.set_cookie("session", ser.dumps({"user_id": uid, "_permanent": True}), domain="localhost")
    assert c.get("/api/me").status_code == 401


# ---- CSV neutralising --------------------------------------------------------------

def test_ratings_csv_neutralises_formulas_in_titles(app):
    app.repos["films"].upsert_many_from_ia([{"identifier": "f1", "title": '=HYPERLINK("http://evil.example","x")'}])
    admin, _ = make_user(app, "a@example.com", ["admin"])
    admin.post("/api/films/f1/ratings", json={"scores": {"originality": 4, "use_of_archive_materials": 3}})
    rows = list(csv.reader(io.StringIO(admin.get("/api/admin/ratings.csv").get_data(as_text=True))))
    assert rows[1][3].startswith("'=HYPERLINK")
    assert rows[1][4:] == ["4", "3"]               # scores stay numeric


def test_csv_safe_helper():
    from server.services.csv_utils import csv_safe
    assert [csv_safe(x) for x in ("=1", "+1", "-1", "@a", "\tx", "\rx", "ok", "", 5, None)] == [
        "'=1", "'+1", "'-1", "'@a", "'\tx", "'\rx", "ok", "", 5, None]
