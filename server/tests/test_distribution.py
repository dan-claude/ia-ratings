"""Handing films out to reviewers (once, randomly, two different reviewers per film), the reset,
hand assignment and the admin progress views."""
import random
from collections import Counter

import pytest

from server.tests.helpers import all_scores, assign, make_user, seed_film


def setup(app, films=10, reviewers=4):
    admin, _ = make_user(app, "admin@example.com", ["admin"])
    revs = [make_user(app, f"r{i}@example.com", ["reviewer"]) for i in range(reviewers)]
    for i in range(films):
        seed_film(app, f"f{i}")
    return admin, revs


def rows(app):
    return [(r["user_id"], r["film_id"], r["status"]) for r in app.db.fetchall("SELECT * FROM assignments")]


# ---- distribute ---------------------------------------------------------------------

def test_every_film_goes_to_exactly_two_different_reviewers(app):
    admin, revs = setup(app, films=25, reviewers=5)
    r = admin.post("/api/admin/distribute")
    assert r.status_code == 200
    d = r.get_json()
    assert d["films"] == 25 and d["reviewers"] == 5 and d["assignments"] == 50
    per_film = Counter(f for _, f, _ in rows(app))
    assert set(per_film.values()) == {2} and len(per_film) == 25
    pairs = [(u, f) for u, f, _ in rows(app)]
    assert len(pairs) == len(set(pairs))                  # never the same reviewer twice on a film
    assert all(s == "assigned" for _, _, s in rows(app))


def test_the_load_is_even_across_reviewers(app):
    admin, revs = setup(app, films=31, reviewers=4)       # 62 reviews / 4 = 15.5 each
    d = admin.post("/api/admin/distribute").get_json()
    per_user = Counter(u for u, _, _ in rows(app))
    assert sorted(per_user.values()) == [15, 15, 16, 16]
    assert d["per_reviewer"] == {"min": 15, "max": 16}


def test_only_reviewers_get_films(app):
    admin, revs = setup(app, films=6, reviewers=3)
    _, jid = make_user(app, "j@example.com", ["judge"])
    _, nid = make_user(app, "n@example.com", [])
    make_user(app, "ar@example.com", ["admin", "reviewer"])   # an admin who is also a reviewer does get films
    admin.post("/api/admin/distribute")
    holders = {u for u, _, _ in rows(app)}
    assert jid not in holders and nid not in holders
    assert len(holders) == 4


def test_it_is_random(app):
    admin, revs = setup(app, films=20, reviewers=6)
    admin.post("/api/admin/distribute")
    first = sorted(rows(app))
    admin.post("/api/admin/distribute/reset", json={"confirm": "RESET"})
    admin.post("/api/admin/distribute")
    assert sorted(rows(app)) != first                      # 20 films x 6 reviewers: a repeat is astronomically unlikely


def test_the_random_source_can_be_seeded_for_a_repeatable_result(app):
    from server.services.distribution_service import DistributionService
    admin, revs = setup(app, films=12, reviewers=4)
    svc = lambda seed: DistributionService(app.repos["users"], app.repos["films"], app.repos["assignments"], random.Random(seed))
    svc(7).distribute()
    a = sorted(rows(app))
    app.repos["assignments"].reset_all()
    svc(7).distribute()
    assert sorted(rows(app)) == a


def test_distribution_runs_once(app):
    admin, _ = setup(app)
    assert admin.post("/api/admin/distribute").status_code == 200
    before = sorted(rows(app))
    r = admin.post("/api/admin/distribute")
    assert r.status_code == 409 and r.get_json()["code"] == "already_distributed"
    assert sorted(rows(app)) == before


def test_preconditions(app):
    admin, _ = make_user(app, "a@example.com", ["admin"])
    r = admin.post("/api/admin/distribute")
    assert r.status_code == 409 and r.get_json()["code"] == "no_films"
    seed_film(app, "f1")
    r = admin.post("/api/admin/distribute")
    assert r.status_code == 409 and r.get_json()["code"] == "too_few_reviewers" and "0" in r.get_json()["error"]
    make_user(app, "r@example.com", ["reviewer"])
    r = admin.post("/api/admin/distribute")
    assert r.status_code == 409 and r.get_json()["code"] == "too_few_reviewers" and "1" in r.get_json()["error"]
    assert rows(app) == []                                 # nothing was handed out
    make_user(app, "r2@example.com", ["reviewer"])
    assert admin.post("/api/admin/distribute").status_code == 200


def test_reviewers_then_see_their_films(app):
    admin, revs = setup(app, films=6, reviewers=3)
    admin.post("/api/admin/distribute")
    c, uid = revs[0]
    mine = {f for u, f, _ in rows(app) if u == uid}
    seen = set()
    for _ in range(len(mine)):
        f = c.get("/api/films/next").get_json()
        seen.add(f["identifier"])
        assert c.post(f"/api/films/{f['identifier']}/ratings", json={"scores": all_scores()}).status_code == 200
    assert len(seen) == len(mine) == 4
    assert c.get("/api/films/next").get_json()["code"] == "all_rated"


# ---- reset --------------------------------------------------------------------------

def test_reset_needs_confirmation_and_clears_everything(app):
    admin, revs = setup(app, films=4, reviewers=2)
    admin.post("/api/admin/distribute")
    c, uid = revs[0]
    c.post(f"/api/films/{c.get('/api/films/next').get_json()['identifier']}/ratings", json={"scores": all_scores(), "comment": "x"})
    app.db.connect().execute("UPDATE films SET in_judges_pool = 1 WHERE id = 1").connection.commit()
    assert admin.post("/api/admin/distribute/reset", json={}).status_code == 400
    assert admin.post("/api/admin/distribute/reset", json={"confirm": "reset"}).status_code == 400
    assert len(rows(app)) == 8
    r = admin.post("/api/admin/distribute/reset", json={"confirm": "RESET"})
    assert r.status_code == 200
    assert r.get_json()["deleted"] == {"rating_scores": 3, "ratings": 1, "assignments": 8, "judges_pool_cleared": 1}
    assert rows(app) == []
    assert app.db.fetchone("SELECT COUNT(*) AS n FROM films")["n"] == 4 and app.db.fetchone("SELECT COUNT(*) AS n FROM users")["n"] == 3
    assert admin.post("/api/admin/distribute").status_code == 200   # can run again


# ---- hand assignment ----------------------------------------------------------------

def test_hand_assign_and_remove(app):
    admin, revs = setup(app, films=2, reviewers=2)
    _, uid = revs[0]
    r = admin.post("/api/admin/assignments", json={"user_id": uid, "identifier": "f0"})
    assert r.status_code == 201 and r.get_json()["added"] is True
    assert admin.post("/api/admin/assignments", json={"user_id": uid, "identifier": "f0"}).status_code == 200   # already had it
    assert len(rows(app)) == 1
    assert admin.delete(f"/api/admin/assignments/{uid}/f0").status_code == 200
    assert rows(app) == []
    assert admin.delete(f"/api/admin/assignments/{uid}/f0").status_code == 404


def test_hand_assign_validation(app):
    admin, revs = setup(app, films=1, reviewers=1)
    _, nid = make_user(app, "n@example.com", ["admin"])
    _, jid = make_user(app, "j@example.com", ["judge"])
    assert admin.post("/api/admin/assignments", json={"user_id": nid, "identifier": "f0"}).status_code == 400     # admin alone doesn't rate
    assert admin.post("/api/admin/assignments", json={"user_id": jid, "identifier": "f0"}).status_code == 201     # a judge can be given a film
    assert admin.post("/api/admin/assignments", json={"user_id": 999, "identifier": "f0"}).status_code == 404
    assert admin.post("/api/admin/assignments", json={"user_id": jid, "identifier": "nope"}).status_code == 404
    for bad in ({}, {"user_id": "1", "identifier": "f0"}, {"user_id": True, "identifier": "f0"}, {"user_id": 1, "identifier": 5}):
        assert admin.post("/api/admin/assignments", json=bad).status_code == 400
    assert admin.delete("/api/admin/assignments/999/nope").status_code == 404


def test_a_rated_film_cannot_be_taken_away(app):
    admin, revs = setup(app, films=1, reviewers=1)
    c, uid = revs[0]
    assign(app, uid, 1)
    c.post("/api/films/f0/ratings", json={"scores": all_scores()})
    assert admin.delete(f"/api/admin/assignments/{uid}/f0").status_code == 409
    assert len(rows(app)) == 1


def test_hand_assigned_films_reach_the_person_even_after_distribution(app):
    admin, revs = setup(app, films=2, reviewers=2)
    admin.post("/api/admin/distribute")
    _, jid = make_user(app, "j@example.com", ["judge"])
    admin.post("/api/admin/assignments", json={"user_id": jid, "identifier": "f1"})
    from server.tests.helpers import login_as
    assert login_as(app, jid).get("/api/films/next").get_json()["identifier"] == "f1"


# ---- progress -----------------------------------------------------------------------

def test_progress_before_anything_is_handed_out(app):
    admin, _ = setup(app, films=3, reviewers=2)
    p = admin.get("/api/admin/progress").get_json()
    assert p["overall"] == {"films": 3, "fully_reviewed": 0, "needing_reviews": 3, "reviews_per_film": 2,
                            "distributed": False, "assignments": {"assigned": 0, "seen": 0, "rated": 0}}
    assert [x["email"] for x in p["people"]] == ["r0@example.com", "r1@example.com"]
    assert all(x["total"] == 0 for x in p["people"])
    assert [f["assignees"] for f in p["films"]] == [[], [], []]


def test_progress_counts_assigned_seen_and_rated(app):
    admin, revs = setup(app, films=4, reviewers=2)
    admin.post("/api/admin/distribute")                      # 2 reviewers: both get all 4 films
    (c0, u0), (c1, u1) = revs
    f = c0.get("/api/films/next").get_json()["identifier"]   # r0 opens one
    c0.post(f"/api/films/{f}/ratings", json={"scores": all_scores()})     # ... and rates it
    c0.get("/api/films/next")                                # r0 opens another (seen)
    g = c1.get("/api/films/next").get_json()["identifier"]   # r1 opens one (seen)
    c1.post(f"/api/films/{g}/ratings", json={"scores": all_scores()})
    p = admin.get("/api/admin/progress").get_json()
    assert p["overall"]["assignments"] == {"assigned": 5, "seen": 1, "rated": 2}     # 8 assignments in all
    people = {x["email"]: x for x in p["people"]}
    assert people["r0@example.com"]["rated"] == 1 and people["r0@example.com"]["seen"] == 1
    assert people["r0@example.com"]["total"] == 4 == sum(people["r0@example.com"][k] for k in ("assigned", "seen", "rated"))
    by = {x["identifier"]: x for x in p["films"]}
    assert by[f]["rated"] >= 1 and len(by[f]["assignees"]) == 2
    assert {a["email"] for a in by[f]["assignees"]} == {"r0@example.com", "r1@example.com"}


def test_a_film_is_fully_reviewed_when_both_reviewers_have_rated(app):
    admin, revs = setup(app, films=2, reviewers=2)
    admin.post("/api/admin/distribute")
    for c, _ in revs:
        c.post("/api/films/f0/ratings", json={"scores": all_scores()})
    p = admin.get("/api/admin/progress").get_json()
    assert p["overall"]["fully_reviewed"] == 1 and p["overall"]["needing_reviews"] == 1
    by = {f["identifier"]: f for f in p["films"]}
    assert by["f0"]["fully_reviewed"] is True and by["f1"]["fully_reviewed"] is False and by["f0"]["rated"] == 2
    assert p["overall"]["distributed"] is True


def test_progress_lists_people_with_films_even_if_their_role_was_removed(app):
    admin, revs = setup(app, films=2, reviewers=2)
    admin.post("/api/admin/distribute")
    _, uid = revs[0]
    app.repos["users"].set_roles(uid, [])
    emails = [x["email"] for x in admin.get("/api/admin/progress").get_json()["people"]]
    assert "r0@example.com" in emails
    assert "admin@example.com" not in emails


def test_admin_routes_require_an_admin(app, client):
    other, uid = make_user(app, "o@example.com", ["reviewer", "judge"])
    calls = [("get", "/api/admin/progress", None), ("post", "/api/admin/distribute", None),
             ("post", "/api/admin/distribute/reset", {"confirm": "RESET"}),
             ("post", "/api/admin/assignments", {"user_id": uid, "identifier": "f"}),
             ("delete", f"/api/admin/assignments/{uid}/f", None)]
    for method, path, body in calls:
        kw = {"json": body} if body is not None else {}
        assert getattr(client, method)(path, **kw).status_code == 401, path
        assert getattr(other, method)(path, **kw).status_code == 403, path
