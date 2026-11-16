"""GitHub OAuth (web application flow) login.

Flow: the browser is sent to GitHub's authorize page with a random `state`;
GitHub redirects back with `?code&state`; we exchange the code for an access
token, read the account's public profile, and find-or-create the local user
keyed on GitHub's numeric account id.

No OAuth scopes are requested: the public profile (id + login) is all we need,
so the app never sees the user's email address or any private data.
"""
import sqlite3
from urllib.parse import urlencode

import requests as _requests

from ..repositories.user_repo import UserRepository

AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
USER_URL = "https://api.github.com/user"
_TIMEOUT = 10


class GitHubAuthError(Exception):
    """The GitHub exchange failed; the message is safe to log, not to show."""


class GitHubAuthService:
    def __init__(self, users: UserRepository, client_id: str, client_secret: str, redirect_uri: str = ""):
        self.users = users
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    def authorize_url(self, state: str) -> str:
        params = {"client_id": self.client_id, "state": state}
        if self.redirect_uri:
            params["redirect_uri"] = self.redirect_uri
        return f"{AUTHORIZE_URL}?{urlencode(params)}"

    def login_with_code(self, code: str) -> int:
        """Complete the flow for an authorization `code`; return the local user id."""
        if not code:
            raise GitHubAuthError("missing code")
        token = self._exchange_code(code)
        github_id, login = self._fetch_profile(token)

        row = self.users.get_by_github_id(github_id)
        if row:
            if row["github_username"] != login:
                self.users.set_github_username(int(row["id"]), login)
            return int(row["id"])
        try:
            return self.users.create_github_user(github_id, login)
        except sqlite3.IntegrityError:
            # A concurrent callback for the same account created it first.
            row = self.users.get_by_github_id(github_id)
            if row:
                return int(row["id"])
            raise

    def _exchange_code(self, code: str) -> str:
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
        }
        if self.redirect_uri:
            payload["redirect_uri"] = self.redirect_uri
        try:
            resp = _requests.post(
                TOKEN_URL, data=payload, headers={"Accept": "application/json"}, timeout=_TIMEOUT
            )
            data = resp.json()
        except (_requests.exceptions.RequestException, ValueError) as exc:
            raise GitHubAuthError("token exchange request failed") from exc
        token = data.get("access_token") if isinstance(data, dict) else None
        if not token:
            err = data.get("error") if isinstance(data, dict) else None
            raise GitHubAuthError(f"token exchange rejected: {err or 'no access_token'}")
        return token

    def _fetch_profile(self, token: str) -> tuple[str, str]:
        try:
            resp = _requests.get(
                USER_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
                timeout=_TIMEOUT,
            )
            data = resp.json()
        except (_requests.exceptions.RequestException, ValueError) as exc:
            raise GitHubAuthError("profile request failed") from exc
        if resp.status_code != 200 or not isinstance(data, dict) or not data.get("id") or not data.get("login"):
            raise GitHubAuthError(f"profile lookup failed: HTTP {resp.status_code}")
        return str(data["id"]), str(data["login"])
