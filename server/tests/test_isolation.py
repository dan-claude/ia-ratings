"""Each test must get its own temporary database (regression test).

Settings used to read env vars once at import time, so every test after the
first silently reused the first test's DB. Two tests registering the same email
would then collide with a 409.
"""
from pathlib import Path

from server.tests.helpers import register


def test_app_uses_this_tests_tmp_db(app, tmp_path):
    assert Path(app.config["DB_PATH"]) == tmp_path / "test.db"


def test_same_email_registers_in_first_test(client):
    assert register(client, "isolation@example.com", "pw").status_code == 200


def test_same_email_registers_in_second_test(client):
    assert register(client, "isolation@example.com", "pw").status_code == 200
