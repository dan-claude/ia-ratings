"""What a reviewer or judge does: open films assigned to them and submit final ratings."""
import pytest

from server.categories import CATEGORY_KEYS
from server.tests.helpers import all_scores, assign, make_user, seed_film


def setup_reviewer(app, roles=("reviewer",), email="r@example.com"):
    c, uid = make_user(app, email, list(roles))
    return c, uid


def test_categories_are_fixed_and_need_login(app, client):
    assert client.get("/api/categories").status_code == 401
    c, _ = setup_reviewer(app)
    cats = c.get("/api/categories").get_json()
    assert [x["key"] for x in cats] == ["aesthetic", "sound", "appeal"] == CATEGORY_KEYS
    assert [x["label"] for x in cats] == ["Aesthetic", "Sound(track)", "Appeal"]
    assert all(x["min"] == 1 and x["max"] == 10 for x in cats)
    assert cats[0]["anchors"] == {"1": "Mash-Up", "5": "Unique and Well Executed", "10": "Unexpected and Surprising"}
    assert cats[0]["description"]


def test_films_require_login(client):
    assert client.get("/api/films/next").status_code == 401
    assert client.get("/api/films/f1").status_code == 401
    assert client.post("/api/films/f1/ratings", json={}).status_code == 401


def test_next_film_explains_why_there_is_none(app):
    nobody, _ = make_user(app, "n@example.com")
    admin, _ = make_user(app, "a@example.com", ["admin"])
    rev, rid = setup_reviewer(app)
    assert nobody.get("/api/films/next").get_json()["code"] == "no_role"
    assert admin.get("/api/films/next").get_json()["code"] == "no_role"           # admin alone doesn't rate
    assert rev.get("/api/films/next").get_json()["code"] == "no_films"
    fid = seed_film(app, "f1")
    r = rev.get("/api/films/next")
    assert r.status_code == 404 and r.get_json()["code"] == "no_assignments"
    assign(app, rid, fid)
    assert rev.get("/api/films/next").status_code == 200
    rev.post("/api/films/f1/ratings", json={"scores": all_scores()})
    assert rev.get("/api/films/next").get_json()["code"] == "all_rated"


def test_next_film_returns_film_details(app):
    rev, rid = setup_reviewer(app)
    fid = seed_film(app, "f1", "A Film", creator="Sam B", description="About it", public_domain_works="Nosferatu",
                    ai_disclosure="Suno for music")
    assign(app, rid, fid)
    f = rev.get("/api/films/next").get_json()
    assert f == {
        "identifier": "f1", "title": "A Film", "creator": "Sam B", "description": "About it",
        "publicDomainWorks": "Nosferatu", "aiDisclosure": "Suno for music",
        "archiveUrl": "https://archive.org/details/f1", "embedUrl": "https://archive.org/embed/f1", "status": "seen",
    }


def test_only_your_own_films_are_shown(app):
    rev, rid = setup_reviewer(app)
    other, oid = setup_reviewer(app, email="o@example.com")
    mine, theirs = seed_film(app, "mine"), seed_film(app, "theirs")
    assign(app, rid, mine)
    assign(app, oid, theirs)
    assert rev.get("/api/films/next").get_json()["identifier"] == "mine"
    assert rev.get("/api/films/theirs").status_code == 404
    assert rev.post("/api/films/theirs/ratings", json={"scores": all_scores()}).status_code == 404
    assert other.get("/api/films/mine").status_code == 404


def test_status_goes_assigned_seen_rated(app):
    rev, rid = setup_reviewer(app)
    fid = seed_film(app, "f1")
    assign(app, rid, fid)
    status = lambda: app.repos["assignments"].get(rid, fid)["status"]
    assert status() == "assigned"
    rev.get("/api/films/next")
    a = app.repos["assignments"].get(rid, fid)
    assert a["status"] == "seen" and a["seen_at"] and not a["rated_at"]
    rev.post("/api/films/f1/ratings", json={"scores": all_scores(), "comment": "Great"})
    a = app.repos["assignments"].get(rid, fid)
    assert a["status"] == "rated" and a["rated_at"]


def test_opening_a_film_by_identifier_also_marks_it_seen(app):
    rev, rid = setup_reviewer(app)
    fid = seed_film(app, "f1")
    assign(app, rid, fid)
    assert rev.get("/api/films/f1").get_json()["status"] == "seen"
    assert app.repos["assignments"].get(rid, fid)["status"] == "seen"


def test_an_opened_but_unfinished_film_comes_back_first(app):
    rev, rid = setup_reviewer(app)
    ids = [seed_film(app, f"f{i}") for i in range(6)]
    for fid in ids:
        assign(app, rid, fid)
    first = rev.get("/api/films/next").get_json()["identifier"]
    for _ in range(10):                       # leaving and coming back always shows the same film
        assert rev.get("/api/films/next").get_json()["identifier"] == first


def test_next_film_is_random_among_the_remaining(app):
    rev, rid = setup_reviewer(app)
    for i in range(8):
        assign(app, rid, seed_film(app, f"f{i}"))
    seen = set()
    for _ in range(30):
        ident = rev.get("/api/films/next").get_json()["identifier"]
        seen.add(ident)
        assert rev.post(f"/api/films/{ident}/ratings", json={"scores": all_scores()}).status_code == 200
        if len(seen) == 8:
            break
    assert len(seen) == 8                      # every film exactly once, in some order
    assert rev.get("/api/films/next").get_json()["code"] == "all_rated"


def test_rating_is_final_and_stored(app):
    rev, rid = setup_reviewer(app)
    fid = seed_film(app, "f1")
    assign(app, rid, fid)
    r = rev.post("/api/films/f1/ratings", json={"scores": {"aesthetic": 10, "sound": 5, "appeal": 1}, "comment": "  Lovely  "})
    assert r.status_code == 200 and r.get_json() == {"ok": True, "total": 16}
    stored = app.repos["ratings"].get_for_user_film(rid, fid)
    assert stored == {"scores": {"aesthetic": 10, "sound": 5, "appeal": 1}, "comment": "Lovely"}
    again = rev.post("/api/films/f1/ratings", json={"scores": all_scores(2)})
    assert again.status_code == 409
    assert app.repos["ratings"].get_for_user_film(rid, fid)["scores"]["aesthetic"] == 10   # unchanged
    # the rated film still opens, showing the person's own rating
    f = rev.get("/api/films/f1").get_json()
    assert f["status"] == "rated" and f["rating"]["comment"] == "Lovely"


def test_comment_is_optional(app):
    rev, rid = setup_reviewer(app)
    fid = seed_film(app, "f1")
    assign(app, rid, fid)
    assert rev.post("/api/films/f1/ratings", json={"scores": all_scores()}).status_code == 200
    assert app.repos["ratings"].get_for_user_film(rid, fid)["comment"] == ""


def test_comment_limit_is_1000_characters(app):
    rev, rid = setup_reviewer(app)
    assign(app, rid, seed_film(app, "f1"))
    assert rev.post("/api/films/f1/ratings", json={"scores": all_scores(), "comment": "x" * 1001}).status_code == 400
    assert rev.post("/api/films/f1/ratings", json={"scores": all_scores(), "comment": 5}).status_code == 400
    assert rev.post("/api/films/f1/ratings", json={"scores": all_scores(), "comment": "<b>é</b>" + "x" * 992}).status_code == 200
    assert app.repos["ratings"].get_for_user_film(rid, 1)["comment"].startswith("<b>é</b>")   # stored verbatim


@pytest.mark.parametrize("scores", [
    None, "x", [], {},
    {"aesthetic": 5, "sound": 5},                              # missing one
    {"aesthetic": 5, "sound": 5, "appeal": 5, "extra": 5},     # unknown category
    {"aesthetic": 0, "sound": 5, "appeal": 5},
    {"aesthetic": 11, "sound": 5, "appeal": 5},
    {"aesthetic": 5.5, "sound": 5, "appeal": 5},
    {"aesthetic": "5", "sound": 5, "appeal": 5},
    {"aesthetic": True, "sound": 5, "appeal": 5},
    {"aesthetic": None, "sound": 5, "appeal": 5},
])
def test_invalid_scores_are_rejected_and_nothing_is_saved(app, scores):
    rev, rid = setup_reviewer(app)
    fid = seed_film(app, "f1")
    assign(app, rid, fid)
    assert rev.post("/api/films/f1/ratings", json={"scores": scores}).status_code == 400
    assert app.repos["ratings"].get_for_user_film(rid, fid) is None
    assert app.repos["assignments"].get(rid, fid)["status"] == "assigned"


def test_the_full_range_1_to_10_is_accepted(app):
    rev, rid = setup_reviewer(app)
    assign(app, rid, seed_film(app, "f1"))
    assign(app, rid, seed_film(app, "f2"))
    assert rev.post("/api/films/f1/ratings", json={"scores": all_scores(1)}).get_json()["total"] == 3
    assert rev.post("/api/films/f2/ratings", json={"scores": all_scores(10)}).get_json()["total"] == 30


def test_judges_rate_too_and_roles_are_checked_on_every_request(app):
    judge, jid = setup_reviewer(app, roles=("judge",), email="j@example.com")
    fid = seed_film(app, "f1")
    assign(app, jid, fid)
    assert judge.get("/api/films/next").status_code == 200
    app.repos["users"].set_roles(jid, ["admin"])               # role taken away
    assert judge.get("/api/films/next").get_json()["code"] == "no_role"
    assert judge.get("/api/films/f1").status_code == 404
    assert judge.post("/api/films/f1/ratings", json={"scores": all_scores()}).status_code == 404


def test_unknown_film(app):
    rev, _ = setup_reviewer(app)
    assert rev.get("/api/films/nope").status_code == 404
    assert rev.post("/api/films/nope/ratings", json={"scores": all_scores()}).status_code == 404


# ---- "my films": the list of everything assigned, with status --------------------------

def test_my_films_lists_assigned_films_with_status_alphabetically(app):
    rev, rid = setup_reviewer(app)
    other, oid = setup_reviewer(app, email="o@example.com")
    for ident, title in (("b", "banana"), ("a", "Apple"), ("c", "Cherry")):
        assign(app, rid, seed_film(app, ident, title, creator=f"Maker {ident}"))
    assign(app, oid, seed_film(app, "x", "Not mine"))
    rev.get("/api/films/b")                                          # opened
    rev.post("/api/films/c/ratings", json={"scores": all_scores()})  # rated
    d = rev.get("/api/me/films").get_json()
    assert d["films"] == [
        {"identifier": "a", "title": "Apple", "creator": "Maker a", "status": "assigned", "round": "reviewers", "in_judges_pool": False},
        {"identifier": "b", "title": "banana", "creator": "Maker b", "status": "seen", "round": "reviewers", "in_judges_pool": False},
        {"identifier": "c", "title": "Cherry", "creator": "Maker c", "status": "rated", "round": "reviewers", "in_judges_pool": False},
    ]


def test_listing_does_not_mark_films_as_seen(app):
    rev, rid = setup_reviewer(app)
    fid = seed_film(app, "f1")
    assign(app, rid, fid)
    rev.get("/api/me/films")
    assert app.repos["assignments"].get(rid, fid)["status"] == "assigned"


def test_my_films_is_for_reviewers_and_judges_only(app, client):
    assert client.get("/api/me/films").status_code == 401
    for roles in ([], ["admin"]):
        c, _ = make_user(app, f"{'-'.join(roles) or 'none'}@example.com", roles)
        assert c.get("/api/me/films").status_code == 403
    j, jid = make_user(app, "j@example.com", ["judge"])
    assign(app, jid, seed_film(app, "f1"))
    assert [f["identifier"] for f in j.get("/api/me/films").get_json()["films"]] == ["f1"]
    empty, _ = setup_reviewer(app, email="empty@example.com")
    assert empty.get("/api/me/films").get_json() == {"films": []}


def test_a_listed_film_opens_and_a_rated_one_shows_the_callers_rating(app):
    rev, rid = setup_reviewer(app)
    assign(app, rid, seed_film(app, "f1", "One"))
    rev.post("/api/films/f1/ratings", json={"scores": {"aesthetic": 9, "sound": 8, "appeal": 7}, "comment": "Fine"})
    f = rev.get("/api/films/f1").get_json()
    assert f["status"] == "rated" and f["rating"] == {"scores": {"aesthetic": 9, "sound": 8, "appeal": 7}, "comment": "Fine"}


def test_my_films_says_which_round_and_whether_the_film_is_in_the_judges_pool(app):
    rev, rid = setup_reviewer(app, roles=("judge",), email="j@example.com")
    fid = seed_film(app, "p1", "Pool film")
    app.repos["films"].set_judges_pool([fid])
    app.repos["assignments"].add(rid, fid, "judges")
    assert rev.get("/api/me/films").get_json()["films"] == [
        {"identifier": "p1", "title": "Pool film", "creator": None, "status": "assigned", "round": "judges", "in_judges_pool": True}]
