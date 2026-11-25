"""Each test must get its own temporary database (regression test).

Settings used to read env vars once at import time, so every test after the
first silently reused the first test's DB. Two tests creating the same email
would then collide.
"""
from pathlib import Path

from server.tests.helpers import make_user


def test_app_uses_this_tests_tmp_db(app, tmp_path):
    assert Path(app.config["DB_PATH"]) == tmp_path / "test.db"


def test_same_email_is_free_in_first_test(app):
    make_user(app, "isolation@example.com")


def test_same_email_is_free_in_second_test(app):
    make_user(app, "isolation@example.com")
