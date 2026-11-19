"""User roles (admin, judge) and judges' film notes."""
import json
import sqlite3

from server.db import Database
from server.tests.helpers import register, login, logout


def make_user(app, email, roles=()):
    from server.tests.helpers import register as reg
    c = app.test_client()
    reg(c, email, "pw")
    row = app.repos["users"].get_by_email(email)
    app.repos["users"].set_roles(int(row["id"]), list(roles))
    return c, int(row["id"])


def seed_film(app, ident="f1"):
    app.repos["films"].upsert_many_from_ia([{"identifier": ident, "title": "T"}])


# ---- roles --------------------------------------------------------------------

def test_new_users_have_no_roles(app, client):
    register(client)
    me = client.get("/api/me").get_json()
    assert me["roles"] == [] and me["is_admin"] is False and me["is_judge"] is False


def test_me_lists_roles(app):
    c, _ = make_user(app, "both@example.com", ["admin", "judge"])
    me = c.get("/api/me").get_json()
    assert me["roles"] == ["admin", "judge"]
    assert me["is_admin"] is True and me["is_judge"] is True


def test_admin_sets_roles_with_exact_list(app):
    admin, admin_id = make_user(app, "a@example.com", ["admin"])
    _, uid = make_user(app, "u@example.com")
    r = admin.put(f"/api/admin/users/{uid}/roles", json={"roles": ["judge"]})
    assert r.status_code == 200 and r.get_json()["roles"] == ["judge"]
    r = admin.put(f"/api/admin/users/{uid}/roles", json={"roles": ["admin", "judge"]})
    assert r.get_json()["roles"] == ["admin", "judge"]
    r = admin.put(f"/api/admin/users/{uid}/roles", json={"roles": []})
    assert r.get_json()["roles"] == []


def test_set_roles_validation(app):
    admin, admin_id = make_user(app, "a@example.com", ["admin"])
    _, uid = make_user(app, "u@example.com")
    assert admin.put(f"/api/admin/users/{uid}/roles", json={"roles": ["wizard"]}).status_code == 400
    assert admin.put(f"/api/admin/users/{uid}/roles", json={"roles": "judge"}).status_code == 400
    assert admin.put(f"/api/admin/users/{uid}/roles", json={}).status_code == 400
    assert admin.put("/api/admin/users/9999/roles", json={"roles": []}).status_code == 404


def test_admin_cannot_remove_own_admin_role(app):
    admin, admin_id = make_user(app, "a@example.com", ["admin"])
    r = admin.put(f"/api/admin/users/{admin_id}/roles", json={"roles": ["judge"]})
    assert r.status_code == 400
    assert "admin" in app.repos["users"].roles_of(app.repos["users"].get_by_id(admin_id))
    # …but may add judge to themselves while staying admin.
    assert admin.put(f"/api/admin/users/{admin_id}/roles", json={"roles": ["admin", "judge"]}).status_code == 200


def test_set_roles_requires_admin(app):
    judge, jid = make_user(app, "j@example.com", ["judge"])
    assert judge.put(f"/api/admin/users/{jid}/roles", json={"roles": ["admin"]}).status_code == 403
    assert app.test_client().put("/api/admin/users/1/roles", json={"roles": []}).status_code == 401


def test_judge_role_does_not_grant_admin(app):
    judge, _ = make_user(app, "j@example.com", ["judge"])
    assert judge.get("/api/admin/db/tables").status_code == 403


def test_make_admin_endpoint_keeps_judge_role(app):
    admin, _ = make_user(app, "a@example.com", ["admin"])
    _, uid = make_user(app, "j@example.com", ["judge"])
    assert admin.post(f"/api/admin/users/{uid}/make-admin").status_code == 200
    assert app.repos["users"].roles_of(app.repos["users"].get_by_id(uid)) == ["admin", "judge"]
    assert admin.post(f"/api/admin/users/{uid}/revoke-admin").status_code == 200
    assert app.repos["users"].roles_of(app.repos["users"].get_by_id(uid)) == ["judge"]


def test_users_dump_includes_is_judge(app):
    admin, _ = make_user(app, "a@example.com", ["admin"])
    make_user(app, "j@example.com", ["judge"])
    rows = admin.get("/api/admin/db/users?order_by=id").get_json()
    assert [r["is_judge"] for r in rows] == [0, 1]


# ---- notes --------------------------------------------------------------------

def test_notes_require_judge(app):
    seed_film(app)
    assert app.test_client().get("/api/films/f1/notes").status_code == 401
    plain, _ = make_user(app, "p@example.com")
    assert plain.get("/api/films/f1/notes").status_code == 403
    assert plain.post("/api/films/f1/notes", json={"text": "hi"}).status_code == 403
    admin, _ = make_user(app, "a@example.com", ["admin"])  # admin alone is not a judge
    assert admin.get("/api/films/f1/notes").status_code == 403


def test_judge_adds_and_lists_notes_oldest_first(app):
    seed_film(app)
    j1, _ = make_user(app, "j1@example.com", ["judge"])
    j2, _ = make_user(app, "j2@example.com", ["judge"])
    assert j1.get("/api/films/f1/notes").get_json() == []
    r = j1.post("/api/films/f1/notes", json={"text": "  Lovely colour work.  "})
    assert r.status_code == 201
    n = r.get_json()
    assert n["text"] == "Lovely colour work."
    assert n["author"] == "j1@example.com"
    assert n["createdAt"].endswith("Z") and "T" in n["createdAt"]
    j2.post("/api/films/f1/notes", json={"text": "Second opinion"})
    notes = j1.get("/api/films/f1/notes").get_json()  # every judge sees every judge's notes
    assert [x["text"] for x in notes] == ["Lovely colour work.", "Second opinion"]
    assert [x["author"] for x in notes] == ["j1@example.com", "j2@example.com"]


def test_notes_are_per_film(app):
    seed_film(app, "f1")
    seed_film(app, "f2")
    j, _ = make_user(app, "j@example.com", ["judge"])
    j.post("/api/films/f1/notes", json={"text": "only on f1"})
    assert j.get("/api/films/f2/notes").get_json() == []


def test_note_author_prefers_ia_then_github_username(app):
    seed_film(app)
    uid = app.repos["users"].create_ia_user("some_ia_user")
    app.repos["users"].set_roles(uid, ["judge"])
    c = app.test_client()
    with c.session_transaction() as s:
        s["user_id"] = uid
    c.post("/api/films/f1/notes", json={"text": "hello"})
    assert c.get("/api/films/f1/notes").get_json()[0]["author"] == "some_ia_user"


def test_note_validation(app):
    seed_film(app)
    j, _ = make_user(app, "j@example.com", ["judge"])
    for bad in ({}, {"text": ""}, {"text": "   "}, {"text": 5}, {"text": None}):
        assert j.post("/api/films/f1/notes", json=bad).status_code == 400
    assert j.post("/api/films/f1/notes", json={"text": "x" * 5001}).status_code == 400
    assert j.post("/api/films/f1/notes", json={"text": "x" * 5000}).status_code == 201
    assert j.post("/api/films/nope/notes", json={"text": "hi"}).status_code == 404
    assert j.get("/api/films/nope/notes").status_code == 404


def test_note_text_is_stored_verbatim_not_as_html(app):
    seed_film(app)
    j, _ = make_user(app, "j@example.com", ["judge"])
    j.post("/api/films/f1/notes", json={"text": "<script>alert(1)</script> 'quoted'; DROP TABLE users;--"})
    assert j.get("/api/films/f1/notes").get_json()[0]["text"].startswith("<script>")
    assert app.db.fetchone("SELECT COUNT(1) AS n FROM users")["n"] == 1


def test_notes_survive_a_resync_of_the_film(app):
    seed_film(app)
    j, _ = make_user(app, "j@example.com", ["judge"])
    j.post("/api/films/f1/notes", json={"text": "keep me"})
    app.repos["films"].upsert_many_from_ia([{"identifier": "f1", "title": "Renamed"}])
    assert [n["text"] for n in j.get("/api/films/f1/notes").get_json()] == ["keep me"]


def test_empty_database_removes_notes(app):
    seed_film(app)
    admin, aid = make_user(app, "a@example.com", ["admin", "judge"])
    admin.post("/api/films/f1/notes", json={"text": "bye"})
    r = admin.post("/api/admin/db/empty", json={"confirm": "EMPTY"})
    assert r.status_code == 200 and r.get_json()["deleted"]["film_notes"] == 1
    assert app.db.fetchone("SELECT COUNT(1) AS n FROM film_notes")["n"] == 0


def test_backup_and_restore_include_notes_and_roles(app):
    seed_film(app)
    admin, aid = make_user(app, "a@example.com", ["admin", "judge"])
    admin.post("/api/films/f1/notes", json={"text": "remember me"})
    backup = json.loads(admin.get("/api/admin/db/backup").data)
    assert backup["tables"]["film_notes"][0]["body"] == "remember me"
    assert backup["tables"]["users"][0]["is_judge"] == 1
    admin.post("/api/films/f1/notes", json={"text": "added after backup"})
    assert admin.post("/api/admin/db/restore", json=backup).status_code == 200
    assert [n["text"] for n in admin.get("/api/films/f1/notes").get_json()] == ["remember me"]


def test_restoring_an_old_backup_without_notes_clears_stale_notes(app):
    seed_film(app)
    admin, aid = make_user(app, "a@example.com", ["admin", "judge"])
    admin.post("/api/films/f1/notes", json={"text": "stale"})
    backup = json.loads(admin.get("/api/admin/db/backup").data)
    del backup["tables"]["film_notes"]
    for u in backup["tables"]["users"]:
        u.pop("is_judge")  # pre-roles backups have no such column
    assert admin.post("/api/admin/db/restore", json=backup).status_code == 200
    assert app.db.fetchone("SELECT COUNT(1) AS n FROM film_notes")["n"] == 0
    row = app.repos["users"].get_by_id(aid)
    assert app.repos["users"].roles_of(row) == ["admin"]  # judge defaults off


# ---- migration ----------------------------------------------------------------

def test_migration_v8_upgrades_an_old_database(tmp_path):
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.executescript("""
      CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now')));
      INSERT INTO users (email, password_hash, is_admin) VALUES ('boss@example.com', 'x', 1);
    """)
    conn.commit()
    conn.close()
    db = Database(path)
    row = db.fetchone("SELECT is_admin, is_judge FROM users WHERE email='boss@example.com'")
    assert row["is_admin"] == 1 and row["is_judge"] == 0  # existing admins stay admins
    assert db.fetchone("SELECT COUNT(1) AS n FROM film_notes")["n"] == 0
    assert db.fetchone("SELECT 1 AS ok FROM schema_migrations WHERE version = 8")["ok"] == 1
    Database(path)  # idempotent: a second startup changes nothing and doesn't fail


# ---- notes.csv export -----------------------------------------------------------

def test_notes_csv_is_admin_only(app):
    assert app.test_client().get("/api/admin/notes.csv").status_code == 401
    judge, _ = make_user(app, "j@example.com", ["judge"])
    assert judge.get("/api/admin/notes.csv").status_code == 403


def test_notes_csv_lists_notes_for_active_collection(app):
    import csv
    import io
    seed_film(app, "f1")
    seed_film(app, "f2")
    j, _ = make_user(app, "j@example.com", ["judge"])
    admin, _ = make_user(app, "a@example.com", ["admin"])
    j.post("/api/films/f2/notes", json={"text": "about f2, with a comma, and\na newline"})
    j.post("/api/films/f1/notes", json={"text": "first"})
    j.post("/api/films/f1/notes", json={"text": "second"})
    r = admin.get("/api/admin/notes.csv")
    assert r.status_code == 200
    assert r.mimetype == "text/csv"
    assert 'filename="notes.csv"' in r.headers["Content-Disposition"]
    rows = list(csv.reader(io.StringIO(r.get_data(as_text=True))))
    assert rows[0] == ["created_at", "author", "identifier", "title", "text"]
    assert [(x[2], x[4]) for x in rows[1:]] == [
        ("f1", "first"), ("f1", "second"), ("f2", "about f2, with a comma, and\na newline"),
    ]
    assert rows[1][1] == "j@example.com"


def test_notes_csv_only_includes_active_collection(app):
    import csv
    import io
    seed_film(app, "f1")
    j, jid = make_user(app, "j@example.com", ["judge"])
    admin, _ = make_user(app, "a@example.com", ["admin"])
    j.post("/api/films/f1/notes", json={"text": "in active collection"})
    # A film in another collection, with a note written directly.
    conn = app.db.connect()
    with conn:
        fid = conn.execute("INSERT INTO films (ia_identifier, title, collection) VALUES ('x1', 'X', 'other-coll')").lastrowid
        conn.execute("INSERT INTO film_notes (film_id, user_id, body) VALUES (?, ?, 'in other collection')", (fid, jid))
    conn.close()
    rows = list(csv.reader(io.StringIO(admin.get("/api/admin/notes.csv").get_data(as_text=True))))
    assert [x[4] for x in rows[1:]] == ["in active collection"]


def test_notes_csv_neutralises_spreadsheet_formulas(app):
    import csv
    import io
    seed_film(app, "f1")
    j, _ = make_user(app, "j@example.com", ["judge"])
    admin, _ = make_user(app, "a@example.com", ["admin"])
    j.post("/api/films/f1/notes", json={"text": '=HYPERLINK("http://evil.example","click")'})
    j.post("/api/films/f1/notes", json={"text": "@SUM(1+1)"})
    j.post("/api/films/f1/notes", json={"text": "-2+3"})
    rows = list(csv.reader(io.StringIO(admin.get("/api/admin/notes.csv").get_data(as_text=True))))
    assert all(x[4].startswith("'") for x in rows[1:])
    # The API itself still returns the text verbatim.
    assert j.get("/api/films/f1/notes").get_json()[0]["text"].startswith("=")


def test_notes_csv_empty_has_header_only(app):
    admin, _ = make_user(app, "a@example.com", ["admin"])
    assert admin.get("/api/admin/notes.csv").get_data(as_text=True).strip() == "created_at,author,identifier,title,text"
