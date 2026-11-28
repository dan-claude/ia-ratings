"""Security hardening: startup secret, proxy setting, body limits, server-side sessions,
CSV neutralising. (The rate limit on the sign-in route is tested with the magic-link login.)"""
import csv
import importlib
import io
import json

import pytest

from server.config import _DEV_SECRET, Settings
from server.tests.helpers import assign, make_user, seed_film


def build_app(monkeypatch, tmp_path, **env):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "s.db"))
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    import server.app as app_module
    importlib.reload(app_module)
    return app_module


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


# ---- proxy setting -----------------------------------------------------------------

def test_proxy_hops_setting_parsing(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "2")
    assert Settings().trusted_proxy_hops == 2
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "garbage")
    assert Settings().trusted_proxy_hops == 0
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "-3")
    assert Settings().trusted_proxy_hops == 0


# ---- request body limits -----------------------------------------------------------

def test_oversized_body_is_rejected(app):
    c, uid = make_user(app, "r@example.com", ["reviewer"])
    r = c.post("/api/films/f1/ratings", json={"scores": {}, "comment": "x" * (2 * 1024 * 1024)})
    assert r.status_code == 413 and r.get_json()["error"]


def test_normal_requests_are_unaffected_by_the_limit(app):
    c, _ = make_user(app, "r@example.com", ["reviewer"])
    assert c.post("/api/films/f1/ratings", json={"scores": {}, "comment": "x" * 900}).status_code == 400


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
        {"id": i + 1, "ia_identifier": f"f{i}", "title": "T" * 100} for i in range(12000)
    ]  # a couple of MB of JSON
    assert len(json.dumps(backup)) > 1024 * 1024
    assert admin.post("/api/admin/db/restore", json=backup).status_code == 200
    assert admin.post("/api/admin/db/empty", json={"confirm": "x" * (2 * 1024 * 1024)}).status_code == 413


# ---- server-side sessions ----------------------------------------------------------

def test_logout_ends_the_session_even_for_a_copied_cookie(app):
    c, _ = make_user(app)
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
    c, _ = make_user(app)
    assert c.get("/api/me").status_code == 200
    conn = app.db.connect()
    with conn:
        conn.execute("UPDATE user_sessions SET created_at = datetime('now', '-9 hours')")
    conn.close()
    assert c.get("/api/me").status_code == 401


def test_starting_a_session_again_replaces_the_old_one(app):
    from server.auth_session import start_session
    c, uid = make_user(app, "u@example.com")
    with c.session_transaction() as s:
        old_sid = s["sid"]
    with app.test_request_context("/"):
        from flask import session
        session["sid"] = old_sid
        start_session(uid)                    # what a fresh sign-in does
        assert session["sid"] != old_sid
    assert not app.repos["sessions"].is_valid(old_sid, uid)
    assert app.db.fetchone("SELECT COUNT(*) AS n FROM user_sessions")["n"] == 1


def test_sessions_are_hashed_and_hidden_from_admin_views(app):
    admin, aid = make_user(app, "a@example.com", ["admin"])
    stored = app.db.fetchone("SELECT sid_hash FROM user_sessions")["sid_hash"]
    assert len(stored) == 64  # sha-256 hex, not the raw token
    assert "user_sessions" not in admin.get("/api/admin/db/tables").get_json()
    assert "user_sessions" not in json.loads(admin.get("/api/admin/db/backup").data)["tables"]
    assert admin.get("/api/admin/db/user_sessions").status_code == 404
    assert "login_links" not in admin.get("/api/admin/db/tables").get_json()
    assert "login_links" not in json.loads(admin.get("/api/admin/db/backup").data)["tables"]


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
    bad = {"app": "ia_ratings", "format_version": 2, "schema_version": 1, "tables": {"users": [{"id": 1, "nope": 1}]}}
    assert admin.post("/api/admin/db/restore", json=bad).status_code == 400
    assert other.get("/api/me").status_code == 200


def test_restore_also_revokes_magic_links(app):
    admin, aid = make_user(app, "a@example.com", ["admin"])
    conn = app.db.connect()
    with conn:
        conn.execute("INSERT INTO login_links (token_hash, user_id, expires_at) VALUES ('h', ?, '2999-01-01')", (aid,))
    conn.close()
    backup = json.loads(admin.get("/api/admin/db/backup").data)
    assert admin.post("/api/admin/db/restore", json=backup).status_code == 200
    assert app.db.fetchone("SELECT COUNT(*) AS n FROM login_links")["n"] == 0


def test_old_cookies_without_a_session_id_are_logged_out(app):
    from flask.sessions import SecureCookieSessionInterface
    _, uid = make_user(app, "u@example.com")
    ser = SecureCookieSessionInterface().get_signing_serializer(app)
    c = app.test_client()
    c.set_cookie("session", ser.dumps({"user_id": uid, "_permanent": True}), domain="localhost")
    assert c.get("/api/me").status_code == 401


# ---- CSV neutralising --------------------------------------------------------------

def test_ratings_csv_neutralises_formulas_in_titles_comments_and_emails(app):
    fid = seed_film(app, "f1", '=HYPERLINK("http://evil.example","x")')
    admin, _ = make_user(app, "a@example.com", ["admin", "reviewer"])
    assign(app, 1, fid)
    admin.post("/api/films/f1/ratings", json={"scores": {"aesthetic": 4, "sound": 3, "appeal": 2}, "comment": "+SUM(A1)"})
    rows = list(csv.reader(io.StringIO(admin.get("/api/admin/ratings.csv").get_data(as_text=True))))
    assert rows[1][3].startswith("'=HYPERLINK")
    assert rows[1][4:8] == ["4", "3", "2", "9"]               # scores stay numeric
    assert rows[1][8] == "'+SUM(A1)"


def test_csv_safe_helper():
    from server.services.csv_utils import csv_safe
    assert [csv_safe(x) for x in ("=1", "+1", "-1", "@a", "\tx", "\rx", "ok", "", 5, None)] == [
        "'=1", "'+1", "'-1", "'@a", "'\tx", "'\rx", "ok", "", 5, None]


def test_csv_safe_looks_past_leading_blanks():
    from server.services.csv_utils import csv_safe
    for evil in (" =HYPERLINK(\"x\")", "\n=1+1", "  \t@SUM(A1)", "\u00a0+1", " \r\n-2"):
        assert csv_safe(evil) == "'" + evil
    assert csv_safe("a = b") == "a = b" and csv_safe("  hello") == "  hello" and csv_safe("   ") == "   "


# ---- browser security headers -------------------------------------------------------

def test_every_response_carries_the_security_headers(app):
    for r in (app.test_client().get("/api/health"), app.test_client().get("/api/me")):
        csp = r.headers["Content-Security-Policy"]
        assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
        assert "frame-src https://archive.org" in csp and "object-src 'none'" in csp
        assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert r.headers["Strict-Transport-Security"] == "max-age=15552000"


def test_local_dev_does_not_send_hsts(monkeypatch, tmp_path):
    m = build_app(monkeypatch, tmp_path, SESSION_SECRET=None)
    r = m.create_app(dev=True).test_client().get("/api/health")
    assert "Strict-Transport-Security" not in r.headers
    assert "Content-Security-Policy" in r.headers


def test_the_client_page_has_no_inline_script():
    import re
    from pathlib import Path
    html = (Path(__file__).resolve().parents[2] / "client" / "index.html").read_text()
    # every <script> must load a file (the CSP forbids inline scripts)
    assert all("src=" in tag for tag in re.findall(r"<script[^>]*>", html))
    assert not re.search(r"<script(?![^>]*src=)[^>]*>\s*\S", html)


# ---- sign-in log line (to check TRUSTED_PROXY_HOPS in production) --------------------

def test_signin_logs_the_client_address_but_not_the_token(app, caplog):
    import logging
    caplog.set_level(logging.INFO)
    r = app.test_client().post("/api/auth/signin", json={"token": "super-secret-token"},
                               headers={"X-Forwarded-For": "203.0.113.9"})
    assert r.status_code == 401
    text = " ".join(rec.getMessage() for rec in caplog.records)
    assert "signin.attempt remote_addr=" in text and "203.0.113.9" in text
    assert "super-secret-token" not in text
