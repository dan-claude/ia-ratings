"""Test helpers for common HTTP calls.

Keep fixtures in conftest.py and put reusable request helpers here.

Import style (IMPORTANT):
    from server.tests.helpers import register, login, logout
"""


def register(client, email="u@example.com", password="pw"):
    """Register a new user and return the Flask test response."""
    return client.post("/api/auth/register", json={"email": email, "password": password})


def login(client, email="u@example.com", password="pw"):
    """Login an existing user and return the Flask test response."""
    return client.post("/api/auth/login", json={"email": email, "password": password})


def logout(client):
    """Logout the current session and return the Flask test response."""
    return client.post("/api/auth/logout")
