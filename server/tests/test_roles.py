"""The three independent roles: admin, reviewer, judge."""
from server.tests.helpers import make_user


def test_new_users_have_no_roles(app):
    c, _ = make_user(app, "a@example.com")
    me = c.get("/api/me").get_json()
    assert me["roles"] == [] and not (me["is_admin"] or me["is_reviewer"] or me["is_judge"])


def test_admin_sets_roles_with_exact_list(app):
    admin, aid = make_user(app, "a@example.com", ["admin"])
    _, uid = make_user(app, "u@example.com")
    r = admin.put(f"/api/admin/users/{uid}/roles", json={"roles": ["reviewer", "judge"]})
    assert r.status_code == 200 and r.get_json()["roles"] == ["reviewer", "judge"]
    r = admin.put(f"/api/admin/users/{uid}/roles", json={"roles": ["admin"]})
    assert r.get_json()["roles"] == ["admin"]          # exactly the list: reviewer and judge are gone
    assert admin.put(f"/api/admin/users/{uid}/roles", json={"roles": []}).get_json()["roles"] == []


def test_roles_are_independent(app):
    admin, _ = make_user(app, "a@example.com", ["admin"])
    for roles in (["admin"], ["reviewer"], ["judge"], ["admin", "judge"], ["reviewer", "judge"], ["admin", "reviewer", "judge"]):
        _, uid = make_user(app, f"{'-'.join(roles)}@example.com")
        assert admin.put(f"/api/admin/users/{uid}/roles", json={"roles": roles}).get_json()["roles"] == roles
    # admin alone is not a rater, a judge alone is not an admin
    c, _ = make_user(app, "j@example.com", ["judge"])
    assert c.get("/api/admin/db/tables").status_code == 403


def test_set_roles_validation(app):
    admin, aid = make_user(app, "a@example.com", ["admin"])
    _, uid = make_user(app, "u@example.com")
    assert admin.put(f"/api/admin/users/{uid}/roles", json={"roles": "judge"}).status_code == 400
    assert admin.put(f"/api/admin/users/{uid}/roles", json={}).status_code == 400
    assert admin.put(f"/api/admin/users/{uid}/roles", json={"roles": ["root"]}).status_code == 400
    assert admin.put("/api/admin/users/9999/roles", json={"roles": ["judge"]}).status_code == 404
    assert app.repos["users"].roles_of(app.repos["users"].get_by_id(uid)) == []


def test_admin_cannot_remove_own_admin_role(app):
    admin, aid = make_user(app, "a@example.com", ["admin"])
    assert admin.put(f"/api/admin/users/{aid}/roles", json={"roles": ["reviewer"]}).status_code == 400
    assert admin.put(f"/api/admin/users/{aid}/roles", json={"roles": ["admin", "reviewer"]}).status_code == 200


def test_set_roles_requires_admin(app, client):
    _, uid = make_user(app, "u@example.com")
    assert client.put(f"/api/admin/users/{uid}/roles", json={"roles": ["admin"]}).status_code == 401
    other, _ = make_user(app, "o@example.com", ["reviewer", "judge"])
    assert other.put(f"/api/admin/users/{uid}/roles", json={"roles": ["admin"]}).status_code == 403


def test_the_old_make_and_revoke_admin_routes_are_gone(app):
    # They let an admin remove their own admin role; PUT .../roles does the job with a guard.
    admin, aid = make_user(app, "a@example.com", ["admin"])
    _, uid = make_user(app, "u@example.com", ["reviewer", "judge"])
    for action in ("make-admin", "revoke-admin"):
        assert admin.post(f"/api/admin/users/{uid}/{action}").status_code in (404, 405)
        assert admin.post(f"/api/admin/users/{aid}/{action}").status_code in (404, 405)
    assert app.repos["users"].roles_of(app.repos["users"].get_by_id(aid)) == ["admin"]
    assert admin.put(f"/api/admin/users/{aid}/roles", json={"roles": []}).status_code == 400


def test_users_dump_has_the_role_columns_and_no_secrets(app):
    admin, _ = make_user(app, "a@example.com", ["admin"])
    make_user(app, "u@example.com", ["reviewer"])
    rows = admin.get("/api/admin/db/users?order_by=id").get_json()
    assert set(rows[0]) == {"id", "email", "is_admin", "is_reviewer", "is_judge", "created_at"}
    assert [(r["email"], r["is_reviewer"]) for r in rows] == [("a@example.com", 0), ("u@example.com", 1)]


def test_emails_are_stored_lowercase_and_unique(app):
    import sqlite3
    import pytest
    make_user(app, "  Mixed@Example.com ")
    assert app.repos["users"].get_by_email("MIXED@example.com")["email"] == "mixed@example.com"
    with pytest.raises(sqlite3.IntegrityError):
        app.repos["users"].create_user("mixed@example.com")
    with pytest.raises(ValueError):
        app.repos["users"].create_user("x@example.com", ["root"])
