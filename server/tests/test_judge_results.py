"""A judge's own ranked list and CSV export of the judges' pool films."""
import csv
import io

from server.tests.helpers import assign, login_as, make_user, seed_film


def pool_setup(app, n_pool=4, judges=1):
    """n_pool pool films (f0..), two reviewers who rated everything the same, and `judges` judges
    who have been given the pool. Returns (admin, [(judge client, uid)])."""
    admin, _ = make_user(app, "admin@example.com", ["admin"])
    revs = [make_user(app, f"r{i}@example.com", ["reviewer"]) for i in range(2)]
    for i in range(n_pool):
        seed_film(app, f"f{i}", f"Film {i}", creator=f"Maker {i}")
    admin.post("/api/admin/distribute")
    for c, _ in revs:
        for i in range(n_pool):
            c.post(f"/api/films/f{i}/ratings", json={"scores": {"aesthetic": 5, "sound": 5, "appeal": 5}})
    js = [make_user(app, f"j{i}@example.com", ["judge"]) for i in range(judges)]
    assert admin.post("/api/admin/judges-pool", json={"count": n_pool}).status_code == 201
    return admin, js


def rate(c, ident, a, s, p, comment=""):
    r = c.post(f"/api/films/{ident}/ratings", json={"scores": {"aesthetic": a, "sound": s, "appeal": p}, "comment": comment})
    assert r.status_code == 200
    return r


def test_the_list_is_ranked_by_total_with_ties_sharing_a_rank_and_listed_alphabetically(app):
    admin, [(j, _)] = pool_setup(app, 5)
    rate(j, "f0", 10, 10, 10, "Best")          # 30
    rate(j, "f1", 5, 5, 5)                     # 15
    rate(j, "f2", 6, 6, 3)                     # 15  (tie with f1)
    rate(j, "f3", 1, 1, 1)                     # 3
    rate(j, "f4", 9, 9, 9)                     # 27
    d = j.get("/api/me/results").get_json()
    assert [(f["identifier"], f["rank"], f["total"]) for f in d["films"]] == [
        ("f0", 1, 30), ("f4", 2, 27), ("f1", 3, 15), ("f2", 3, 15), ("f3", 5, 3)]
    assert d["pool_size"] == 5 and d["rated"] == 5 and d["complete"] is True
    top = d["films"][0]
    assert top == {"identifier": "f0", "title": "Film 0", "creator": "Maker 0", "archiveUrl": "https://archive.org/details/f0",
                   "scores": {"aesthetic": 10, "sound": 10, "appeal": 10}, "total": 30, "comment": "Best", "rank": 1}


def test_partial_progress_is_not_complete(app):
    admin, [(j, _)] = pool_setup(app, 3)
    assert j.get("/api/me/results").get_json() == {"pool_size": 3, "rated": 0, "complete": False, "films": []}
    rate(j, "f1", 4, 4, 4)
    d = j.get("/api/me/results").get_json()
    assert (d["rated"], d["complete"], [f["identifier"] for f in d["films"]]) == (1, False, ["f1"])


def test_only_the_callers_own_ratings_of_pool_films_are_listed(app):
    admin, [(j1, _), (j2, _)] = pool_setup(app, 2, judges=2)
    rate(j1, "f0", 10, 10, 10)
    rate(j2, "f0", 1, 1, 1)
    assert [f["total"] for f in j1.get("/api/me/results").get_json()["films"]] == [30]
    assert [f["total"] for f in j2.get("/api/me/results").get_json()["films"]] == [3]


def test_films_outside_the_pool_are_not_listed(app):
    admin, [(j, jid)] = pool_setup(app, 2)
    other = seed_film(app, "extra", "Extra")
    app.repos["users"].set_roles(jid, ["judge", "reviewer"])
    assign(app, jid, other)
    rate(j, "extra", 9, 9, 9)
    assert [f["identifier"] for f in j.get("/api/me/results").get_json()["films"]] == []


def test_a_judge_who_already_reviewed_a_pool_film_has_that_rating_in_their_list(app):
    admin, _ = make_user(app, "admin@example.com", ["admin"])
    a, aid = make_user(app, "a@example.com", ["reviewer"])
    b, bid = make_user(app, "b@example.com", ["reviewer"])
    for i in range(2):
        seed_film(app, f"f{i}", f"Film {i}")
    admin.post("/api/admin/distribute")
    for c in (a, b):
        c.post("/api/films/f0/ratings", json={"scores": {"aesthetic": 8, "sound": 8, "appeal": 8}, "comment": "reviewing round"})
        c.post("/api/films/f1/ratings", json={"scores": {"aesthetic": 2, "sound": 2, "appeal": 2}})
    app.repos["users"].set_roles(aid, ["reviewer", "judge"])
    assert admin.post("/api/admin/judges-pool", json={"count": 1}).status_code == 201     # pool: f0
    d = a.get("/api/me/results").get_json()
    assert d["complete"] is True and d["pool_size"] == 1
    assert (d["films"][0]["identifier"], d["films"][0]["total"], d["films"][0]["comment"]) == ("f0", 24, "reviewing round")
    assert a.get("/api/films/next").get_json()["code"] == "all_rated"                      # nothing more to rate


def test_judges_only(app, client):
    assert client.get("/api/me/results").status_code == 401
    assert client.get("/api/me/results.csv").status_code == 401
    for roles in ([], ["reviewer"], ["admin"], ["admin", "reviewer"]):
        c, _ = make_user(app, f"{'-'.join(roles) or 'none'}@example.com", roles)
        assert c.get("/api/me/results").status_code == 403, roles
        assert c.get("/api/me/results.csv").status_code == 403, roles
    c, _ = make_user(app, "j@example.com", ["admin", "judge"])
    assert c.get("/api/me/results").status_code == 200


def test_the_export_is_a_csv_of_the_same_list(app):
    admin, [(j, _)] = pool_setup(app, 3)
    rate(j, "f0", 10, 9, 8, 'Lovely, "quoted"\nsecond line')
    rate(j, "f1", 5, 5, 5, "=HYPERLINK(\"http://evil.example\")")
    rate(j, "f2", 1, 2, 3)
    r = j.get("/api/me/results.csv")
    assert r.mimetype == "text/csv" and 'filename="my_ratings.csv"' in r.headers["Content-Disposition"]
    rows = list(csv.reader(io.StringIO(r.get_data(as_text=True))))
    assert rows[0] == ["rank", "title", "creator", "aesthetic", "sound", "appeal", "total", "comment"]
    assert rows[1] == ["1", "Film 0", "Maker 0", "10", "9", "8", "27", 'Lovely, "quoted"\nsecond line']
    assert rows[2][7] == "'=HYPERLINK(\"http://evil.example\")"                        # formulas neutralised
    assert rows[3] == ["3", "Film 2", "Maker 2", "1", "2", "3", "6", ""]
    assert len(rows) == 4


def test_judges_never_see_other_peoples_scores(app):
    admin, [(j, _)] = pool_setup(app, 2)
    rate(j, "f0", 7, 7, 7)
    text = j.get("/api/me/results").get_data(as_text=True) + j.get("/api/films/next").get_data(as_text=True)
    assert "average" not in text and "reviews" not in text and "r0@example.com" not in text
