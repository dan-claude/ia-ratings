"""GitHub OAuth login. GitHub's HTTP endpoints are replaced with fakes."""
import importlib
from urllib.parse import urlparse, parse_qs

import pytest

from server.services import github_auth_service as gh


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


@pytest.fixture()
def gh_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.setenv("AUTH_SCHEME", "local")
    monkeypatch.setenv("GITHUB_CLIENT_ID", "cid")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "csecret")
    import server.app as app_module
    importlib.reload(app_module)
    app = app_module.create_app()
    app.config.update(TESTING=True)
    return app


@pytest.fixture()
def gh_client(gh_app):
    return gh_app.test_client()


@pytest.fixture()
def fake_github(monkeypatch):
    """Control what GitHub returns; records the calls made."""
    state = {
        "token": {"access_token": "tok"},
        "profile": FakeResponse({"id": 4242, "login": "octocat"}),
        "calls": [],
    }

    def post(url, data=None, headers=None, timeout=None):
        state["calls"].append(("post", url, data))
        return FakeResponse(state["token"])

    def get(url, headers=None, timeout=None):
        state["calls"].append(("get", url, headers))
        return state["profile"]

    monkeypatch.setattr(gh._requests, "post", post)
    monkeypatch.setattr(gh._requests, "get", get)
    return state


def _start(client):
    """Hit /login and return the state GitHub would echo back."""
    r = client.get("/api/auth/github/login")
    assert r.status_code == 302
    q = parse_qs(urlparse(r.headers["Location"]).query)
    return r, q["state"][0]


def test_disabled_by_default(client):
    assert client.get("/api/config").get_json()["oauth_providers"] == []
    assert client.get("/api/auth/github/login").status_code == 404
    assert client.get("/api/auth/github/callback?code=x&state=y").status_code == 404


def test_config_lists_github_when_configured(gh_client):
    cfg = gh_client.get("/api/config").get_json()
    assert cfg["oauth_providers"] == ["github"]
    assert cfg["auth_scheme"] == "local"  # password login still offered


def test_login_redirects_to_github_with_state(gh_client):
    r, state = _start(gh_client)
    u = urlparse(r.headers["Location"])
    q = parse_qs(u.query)
    assert f"{u.scheme}://{u.netloc}{u.path}" == "https://github.com/login/oauth/authorize"
    assert q["client_id"] == ["cid"]
    assert len(state) >= 32
    assert "redirect_uri" not in q  # GitHub uses the URL registered on the app
    assert "scope" not in q         # public profile only


def test_callback_creates_user_and_logs_in(gh_client, fake_github):
    _, state = _start(gh_client)
    r = gh_client.get(f"/api/auth/github/callback?code=abc&state={state}")
    assert r.status_code == 302 and r.headers["Location"].endswith("/")

    me = gh_client.get("/api/me")
    assert me.status_code == 200
    assert me.get_json()["email"] == "4242+octocat@users.noreply.github.com"

    token_call = next(c for c in fake_github["calls"] if c[0] == "post")
    assert token_call[2]["code"] == "abc" and token_call[2]["client_secret"] == "csecret"


def test_second_login_reuses_user_and_tracks_rename(gh_app, gh_client, fake_github):
    _, s1 = _start(gh_client)
    gh_client.get(f"/api/auth/github/callback?code=a&state={s1}")
    first_id = gh_client.get("/api/me").get_json()["id"]
    gh_client.post("/api/auth/logout")

    fake_github["profile"] = FakeResponse({"id": 4242, "login": "renamed"})
    _, s2 = _start(gh_client)
    gh_client.get(f"/api/auth/github/callback?code=b&state={s2}")
    assert gh_client.get("/api/me").get_json()["id"] == first_id

    row = gh_app.repos["users"].get_by_github_id("4242")
    assert row["github_username"] == "renamed"


def test_bad_or_missing_state_rejected(gh_client, fake_github):
    r = gh_client.get("/api/auth/github/callback?code=abc&state=nope")
    assert r.headers["Location"] == "/?auth_error=github_state"
    _, state = _start(gh_client)
    r = gh_client.get("/api/auth/github/callback?code=abc&state=wrong")
    assert r.headers["Location"] == "/?auth_error=github_state"
    assert gh_client.get("/api/me").status_code == 401
    assert not fake_github["calls"]  # never talked to GitHub


def test_state_is_single_use(gh_client, fake_github):
    _, state = _start(gh_client)
    gh_client.get(f"/api/auth/github/callback?code=abc&state={state}")
    gh_client.post("/api/auth/logout")
    r = gh_client.get(f"/api/auth/github/callback?code=abc&state={state}")
    assert r.headers["Location"] == "/?auth_error=github_state"
    assert gh_client.get("/api/me").status_code == 401


def test_user_cancelled_on_github(gh_client, fake_github):
    _, state = _start(gh_client)
    r = gh_client.get(f"/api/auth/github/callback?error=access_denied&state={state}")
    assert r.headers["Location"] == "/?auth_error=github_denied"
    assert gh_client.get("/api/me").status_code == 401


def test_token_exchange_rejected(gh_client, fake_github):
    fake_github["token"] = {"error": "bad_verification_code"}
    _, state = _start(gh_client)
    r = gh_client.get(f"/api/auth/github/callback?code=abc&state={state}")
    assert r.headers["Location"] == "/?auth_error=github_failed"
    assert gh_client.get("/api/me").status_code == 401


def test_profile_lookup_failure(gh_client, fake_github):
    fake_github["profile"] = FakeResponse({"message": "Bad credentials"}, status=401)
    _, state = _start(gh_client)
    r = gh_client.get(f"/api/auth/github/callback?code=abc&state={state}")
    assert r.headers["Location"] == "/?auth_error=github_failed"


def test_callback_rotates_existing_session(gh_client, fake_github):
    gh_client.post("/api/auth/register", json={"email": "p@example.com", "password": "pw"})
    pw_id = gh_client.get("/api/me").get_json()["id"]
    _, state = _start(gh_client)
    gh_client.get(f"/api/auth/github/callback?code=abc&state={state}")
    assert gh_client.get("/api/me").get_json()["id"] != pw_id
