"""Rankings by the reviewers' average score, and the judges' pool (preview, tie rule, confirm)."""
import csv
import io
from fractions import Fraction

import pytest

from server.services.ranking_service import _ranked
from server.tests.helpers import all_scores, assign, login_as, make_user, seed_film


def build(app, totals, reviewers=2):
    """Films f0.. with the given per-reviewer score for each film, distributed to `reviewers` reviewers.

    totals: list (one per film) of lists (one per reviewer) of a single score used in every category,
    so a person's total is 3x that score. None = that reviewer has not rated the film.
    Returns (admin client, [reviewer clients])."""
    admin, _ = make_user(app, "admin@example.com", ["admin"])
    revs = [make_user(app, f"r{i}@example.com", ["reviewer"]) for i in range(reviewers)]
    for i in range(len(totals)):
        seed_film(app, f"f{i}", f"Film {i}")
    assert admin.post("/api/admin/distribute").status_code == 200
    for fi, per_reviewer in enumerate(totals):
        for (c, _), score in zip(revs, per_reviewer):
            if score is not None:
                assert c.post(f"/api/films/f{fi}/ratings", json={"scores": all_scores(score)}).status_code == 200
    return admin, [c for c, _ in revs]


def idents(films):
    return [f["identifier"] for f in films]


# ---- ranking --------------------------------------------------------------------------

def test_films_are_ranked_by_average_highest_first_with_exact_numbers(app):
    admin, _ = build(app, [[5, 5], [9, 7], [2, 4], [8, 8]])
    d = admin.get("/api/admin/rankings").get_json()
    assert idents(d["films"]) == ["f1", "f3", "f0", "f2"]          # f1 and f3 tie: alphabetical
    top = d["films"][0]
    assert (top["rank"], top["average"], top["reviews"], top["total"]) == (1, 24.0, 2, 48)   # 3 categories x 8 x 2 reviewers
    assert [f["average"] for f in d["films"]] == [24.0, 24.0, 15.0, 9.0]
    assert d["overall"]["fully_reviewed"] == 4


def test_equal_averages_share_a_rank_and_are_listed_alphabetically(app):
    admin, _ = build(app, [[5, 5], [8, 8], [5, 5], [8, 8], [1, 1]])
    films = admin.get("/api/admin/rankings").get_json()["films"]
    assert [(f["identifier"], f["rank"]) for f in films] == [("f1", 1), ("f3", 1), ("f0", 3), ("f2", 3), ("f4", 5)]


def test_unrated_films_come_last_and_are_unranked(app):
    admin, _ = build(app, [[6, 6], [None, None]])
    films = admin.get("/api/admin/rankings").get_json()["films"]
    assert [(f["identifier"], f["rank"], f["average"]) for f in films] == [("f0", 1, 18.0), ("f1", None, None)]


def test_averages_are_compared_exactly_not_as_rounded_decimals():
    rows = [
        {"identifier": "b", "title": "B", "reviews": 3000, "total": 40009},   # 13.3363...
        {"identifier": "a", "title": "A", "reviews": 100, "total": 1334},     # 13.34 exactly
        {"identifier": "c", "title": "C", "reviews": 100, "total": 1334},
    ]
    ranked = _ranked([dict(r) for r in rows])
    assert [(r["identifier"], r["rank"]) for r in ranked] == [("a", 1), ("c", 1), ("b", 3)]
    assert round(40009 / 3000, 2) == round(1334 / 100, 2) == 13.34                # decimals alone would call it a tie
    assert Fraction(1334, 100) > Fraction(40009, 3000)


def test_judges_ratings_do_not_change_the_reviewers_average(app):
    admin, revs = build(app, [[5, 5], [9, 9]])
    assert admin.post("/api/admin/judges-pool", json={"count": 1}).status_code == 201
    _, jid = make_user(app, "j@example.com", ["judge"])
    admin.post("/api/admin/judges-pool/assign")
    j = login_as(app, jid)
    assert j.post("/api/films/f1/ratings", json={"scores": all_scores(1)}).status_code == 200
    f1 = next(f for f in admin.get("/api/admin/rankings").get_json()["films"] if f["identifier"] == "f1")
    assert (f1["reviews"], f1["average"]) == (2, 27.0)


def test_rankings_csv_has_every_film_detail(app):
    admin, _ = make_user(app, "a@example.com", ["admin"])
    make_user(app, "r1@example.com", ["reviewer"]); c2, _ = make_user(app, "r2@example.com", ["reviewer"])
    seed_film(app, "f0", "=Evil", creator="Sam", description="Desc", public_domain_works="Nosferatu", ai_disclosure="Suno")
    admin.post("/api/admin/distribute")
    r = admin.get("/api/admin/rankings.csv")
    assert r.mimetype == "text/csv" and "rankings.csv" in r.headers["Content-Disposition"]
    rows = list(csv.reader(io.StringIO(r.get_data(as_text=True))))
    assert rows[0] == ["rank", "title", "creator", "average", "reviews", "total", "identifier", "description",
                       "public_domain_works", "ai_disclosure", "in_judges_pool"]
    assert rows[1] == ["", "'=Evil", "Sam", "", "0", "0", "f0", "Desc", "Nosferatu", "Suno", "no"]


def test_fully_reviewed_counts_only_the_reviewers_round(app):
    admin, revs = build(app, [[5, 5], [6, 6]])
    admin.post("/api/admin/judges-pool", json={"count": 2})
    _, jid = make_user(app, "j@example.com", ["judge"])
    admin.post("/api/admin/judges-pool/assign")
    login_as(app, jid).post("/api/films/f0/ratings", json={"scores": all_scores()})
    o = admin.get("/api/admin/progress").get_json()
    assert o["overall"]["fully_reviewed"] == 2
    f0 = next(f for f in o["films"] if f["identifier"] == "f0")
    assert f0["rated"] == 2 and len(f0["assignees"]) == 3 and {a["round"] for a in f0["assignees"]} == {"reviewers", "judges"}


# ---- preview --------------------------------------------------------------------------

def test_preview_is_blocked_until_every_film_has_both_reviews(app):
    admin, revs = build(app, [[5, 5], [6, None], [None, None]])
    r = admin.get("/api/admin/judges-pool/preview?count=1")
    assert r.status_code == 409
    d = r.get_json()
    assert d["code"] == "reviews_missing"
    assert "1 of 3 films fully reviewed; 2 still need at least one review" in d["error"]
    assert d["overall"]["needing_reviews"] == 2
    assert d["missing"] == [{"identifier": "f1", "title": "Film 1", "rated": 1, "needed": 2},
                            {"identifier": "f2", "title": "Film 2", "rated": 0, "needed": 2}]
    # confirming is blocked the same way, and nothing changes
    assert admin.post("/api/admin/judges-pool", json={"count": 1}).status_code == 409
    assert app.db.fetchone("SELECT COUNT(*) AS n FROM films WHERE in_judges_pool = 1")["n"] == 0


def test_preview_blocked_with_no_films_or_no_distribution(app):
    admin, _ = make_user(app, "a@example.com", ["admin"])
    assert admin.get("/api/admin/judges-pool/preview").get_json()["code"] == "no_films"
    seed_film(app, "f0")
    assert admin.get("/api/admin/judges-pool/preview").get_json()["code"] == "reviews_missing"


def test_preview_lists_the_top_films_with_their_averages_and_changes_nothing(app):
    admin, _ = build(app, [[5, 5], [9, 7], [2, 4], [8, 8], [1, 1]])
    d = admin.get("/api/admin/judges-pool/preview?count=2").get_json()
    assert d["count"] == 2 and d["valid"] is True and d["tie"] is None and d["total_films"] == 5
    assert [(f["identifier"], f["average"], f["rank"]) for f in d["films"]] == [("f1", 24.0, 1), ("f3", 24.0, 1)]
    assert app.db.fetchone("SELECT COUNT(*) AS n FROM films WHERE in_judges_pool = 1")["n"] == 0
    assert app.db.fetchone("SELECT COUNT(*) AS n FROM assignments WHERE round = 'judges'")["n"] == 0


def test_a_tie_at_the_cutoff_is_not_valid_and_nearby_valid_numbers_are_offered(app):
    # averages (x3 per rating): f0 30, f1 30, f2 24, f3 24, f4 24, f5 12
    admin, _ = build(app, [[10, 10], [10, 10], [8, 8], [8, 8], [8, 8], [4, 4]])
    d = admin.get("/api/admin/judges-pool/preview?count=3").get_json()      # f2 vs f3 tie at 24
    assert d["valid"] is False
    assert d["tie"]["nearest_valid_counts"] == {"lower": 2, "higher": 5}
    assert "same average" in d["tie"]["message"]
    assert admin.get("/api/admin/judges-pool/preview?count=2").get_json()["valid"] is True
    assert admin.get("/api/admin/judges-pool/preview?count=5").get_json()["valid"] is True
    assert admin.get("/api/admin/judges-pool/preview?count=6").get_json()["valid"] is True     # everything: no film after the cut
    r = admin.post("/api/admin/judges-pool", json={"count": 3})
    assert r.status_code == 409 and r.get_json()["code"] == "tie_at_cutoff"
    assert app.db.fetchone("SELECT COUNT(*) AS n FROM films WHERE in_judges_pool = 1")["n"] == 0


def test_count_validation_and_default(app):
    admin, _ = build(app, [[5, 5], [6, 6], [7, 7]])
    assert admin.get("/api/admin/judges-pool/preview").get_json()["count"] == 3        # default 20, capped at the number of films
    for bad in ("0", "4", "-1", "abc", "1.5", ""):
        assert admin.get(f"/api/admin/judges-pool/preview?count={bad}").status_code == 400, bad
    for bad in (0, 4, "2", True, 2.5):
        assert admin.post("/api/admin/judges-pool", json={"count": bad}).status_code == 400, bad


# ---- confirm --------------------------------------------------------------------------

def test_confirm_sets_the_pool_and_gives_every_judge_every_pool_film(app):
    admin, _ = build(app, [[5, 5], [9, 9], [2, 2], [8, 7]])
    judges = [make_user(app, f"j{i}@example.com", ["judge"]) for i in range(3)]
    r = admin.post("/api/admin/judges-pool", json={"count": 2})
    assert r.status_code == 201
    assert r.get_json() == {"ok": True, "count": 2, "judges": 3, "assigned": 6}
    pool = {row["ia_identifier"] for row in app.db.fetchall("SELECT ia_identifier FROM films WHERE in_judges_pool = 1")}
    assert pool == {"f1", "f3"}
    for c, uid in judges:
        mine = app.db.fetchall("SELECT f.ia_identifier AS i, a.round FROM assignments a JOIN films f ON f.id=a.film_id WHERE a.user_id=?", (uid,))
        assert {(m["i"], m["round"]) for m in mine} == {("f1", "judges"), ("f3", "judges")}
        assert c.get("/api/films/next").status_code == 200
    # judges are not shown anything about ratings
    nxt = judges[0][0].get("/api/films/next").get_json()
    assert not {"average", "reviews", "total", "rank", "rating"} & set(nxt)
    status = admin.get("/api/admin/judges-pool").get_json()
    assert status["exists"] and idents(status["films"]) == ["f1", "f3"]
    assert [j["films"] for j in status["judges"]] == [2, 2, 2]


def test_confirm_only_once(app):
    admin, _ = build(app, [[5, 5], [9, 9]])
    assert admin.post("/api/admin/judges-pool", json={"count": 1}).status_code == 201
    r = admin.post("/api/admin/judges-pool", json={"count": 2})
    assert r.status_code == 409 and r.get_json()["code"] == "pool_already_set"


def test_a_judge_who_already_reviewed_a_pool_film_keeps_that_rating_and_does_not_rate_it_again(app):
    admin, revs = build(app, [[5, 5], [9, 9]])
    rev_uid = app.repos["users"].get_by_email("r0@example.com")["id"]
    app.repos["users"].set_roles(rev_uid, ["reviewer", "judge"])      # r0 is a reviewer and a judge
    admin.post("/api/admin/judges-pool", json={"count": 1})           # pool: f1
    a = app.repos["assignments"].get(rev_uid, 2)
    assert a["status"] == "rated"                                      # their reviewing-round rating, untouched
    assert app.db.fetchone("SELECT round FROM assignments WHERE user_id=? AND film_id=2", (rev_uid,))["round"] == "reviewers"
    assert app.repos["ratings"].get_for_user_film(rev_uid, 2)["scores"]["appeal"] == 9
    c = login_as(app, rev_uid)
    assert c.get("/api/films/next").get_json()["code"] == "all_rated"          # nothing left to rate
    assert c.post("/api/films/f1/ratings", json={"scores": all_scores(1)}).status_code == 409
    assert app.repos["ratings"].get_for_user_film(rev_uid, 2)["scores"]["appeal"] == 9


def test_assigning_the_pool_again_reaches_judges_added_later_and_is_idempotent(app):
    admin, _ = build(app, [[5, 5], [9, 9]])
    admin.post("/api/admin/judges-pool", json={"count": 2})
    _, jid = make_user(app, "late@example.com", ["judge"])
    assert app.db.fetchone("SELECT COUNT(*) AS n FROM assignments WHERE user_id=?", (jid,))["n"] == 0
    r = admin.post("/api/admin/judges-pool/assign").get_json()
    assert r["assigned"] == 2 and r["judges"] == 1 and r["films"] == 2
    assert admin.post("/api/admin/judges-pool/assign").get_json()["assigned"] == 0


def test_assign_without_a_pool(app):
    admin, _ = build(app, [[5, 5]])
    r = admin.post("/api/admin/judges-pool/assign")
    assert r.status_code == 409 and r.get_json()["code"] == "no_pool"


def test_clearing_the_pool(app):
    admin, _ = build(app, [[5, 5], [9, 9]])
    _, jid = make_user(app, "j@example.com", ["judge"])
    admin.post("/api/admin/judges-pool", json={"count": 1})
    assert admin.delete("/api/admin/judges-pool").get_json() == {"ok": True, "removed_assignments": 1}
    assert app.db.fetchone("SELECT COUNT(*) AS n FROM films WHERE in_judges_pool = 1")["n"] == 0
    assert app.db.fetchone("SELECT COUNT(*) AS n FROM assignments WHERE user_id=?", (jid,))["n"] == 0
    assert admin.post("/api/admin/judges-pool", json={"count": 2}).status_code == 201     # can choose again


def test_the_pool_cannot_be_cleared_once_a_judge_has_rated(app):
    admin, _ = build(app, [[5, 5], [9, 9]])
    _, jid = make_user(app, "j@example.com", ["judge"])
    admin.post("/api/admin/judges-pool", json={"count": 1})
    login_as(app, jid).post("/api/films/f1/ratings", json={"scores": all_scores()})
    r = admin.delete("/api/admin/judges-pool")
    assert r.status_code == 409 and r.get_json()["code"] == "judges_have_rated"
    assert app.db.fetchone("SELECT COUNT(*) AS n FROM films WHERE in_judges_pool = 1")["n"] == 1


def test_hand_assigning_a_pool_film_to_a_judge_uses_the_judges_round(app):
    admin, _ = build(app, [[5, 5], [9, 9]])
    admin.post("/api/admin/judges-pool", json={"count": 1})
    _, jid = make_user(app, "late@example.com", ["judge"])
    _, rid = make_user(app, "late-r@example.com", ["reviewer"])
    admin.post("/api/admin/assignments", json={"user_id": jid, "identifier": "f1"})
    admin.post("/api/admin/assignments", json={"user_id": rid, "identifier": "f0"})
    rounds = {(r["user_id"], r["round"]) for r in app.db.fetchall("SELECT user_id, round FROM assignments WHERE user_id IN (?, ?)", (jid, rid))}
    assert rounds == {(jid, "judges"), (rid, "reviewers")}


def test_reset_clears_the_pool_too(app):
    admin, _ = build(app, [[5, 5], [9, 9]])
    admin.post("/api/admin/judges-pool", json={"count": 1})
    admin.post("/api/admin/distribute/reset", json={"confirm": "RESET"})
    assert app.db.fetchone("SELECT COUNT(*) AS n FROM films WHERE in_judges_pool = 1")["n"] == 0


def test_every_route_is_admin_only(app, client):
    other, uid = make_user(app, "o@example.com", ["reviewer", "judge"])
    calls = [("get", "/api/admin/rankings"), ("get", "/api/admin/rankings.csv"), ("get", "/api/admin/judges-pool"),
             ("get", "/api/admin/judges-pool/preview"), ("post", "/api/admin/judges-pool"),
             ("post", "/api/admin/judges-pool/assign"), ("delete", "/api/admin/judges-pool")]
    for method, path in calls:
        assert getattr(client, method)(path).status_code == 401, path
        assert getattr(other, method)(path).status_code == 403, path
