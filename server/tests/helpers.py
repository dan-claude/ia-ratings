"""Test helpers. Keep fixtures in conftest.py and reusable setup here.

Import style (IMPORTANT):
    from server.tests.helpers import make_user, seed_film, assign

There is no password login any more (people sign in with a magic link), so tests
create users directly and give their test client a server-side session.
"""
from server.categories import CATEGORY_KEYS


def make_user(app, email="u@example.com", roles=()):
    """Create a user holding `roles` and return (logged-in test client, user id)."""
    uid = app.repos["users"].create_user(email, list(roles))
    return login_as(app, uid), uid


def login_as(app, uid):
    """A new test client logged in as user `uid`."""
    c = app.test_client()
    with c.session_transaction() as s:
        s["user_id"] = uid
        s["sid"] = app.repos["sessions"].create(uid)
        s.permanent = True
    return c


def seed_film(app, ident="film1", title=None, **fields):
    """Insert a film and return its id."""
    cols = {"title": title or ident.title(), **fields}
    names = ", ".join(["ia_identifier", *cols])
    marks = ", ".join("?" * (len(cols) + 1))
    conn = app.db.connect()
    try:
        with conn:
            cur = conn.execute(f"INSERT INTO films ({names}) VALUES ({marks})", [ident, *cols.values()])
        return int(cur.lastrowid)
    finally:
        conn.close()


def assign(app, uid, film_id):
    app.repos["assignments"].add(uid, film_id)


def all_scores(n=7):
    return {k: n for k in CATEGORY_KEYS}
