"""CSV (spreadsheet) import of films. Sample data is invented but shaped like a real submissions sheet."""
import threading

import pytest

from server.services import import_service
from server.services.import_service import parse_archive_url, parse_csv, suggest_mapping, validate_mapping
from server.tests.helpers import make_user, assign, seed_film

HEADER = (
    "Timestamp,Your name,Your email,URL/Link to your film at archive.org,Where are you located?,"
    "Your age,Description of your film / Artist's Statement,AI tools used"
)

CSV_TEXT = "\n".join([
    HEADER,
    # junk pasted into the link column -> skipped
    '11/10/2026 18:02:34,Pat A,pat@example.com,"Calculation reference 336A41C34 carried out on 07 July 2026",Scotland,55,Blank,',
    # multi-line quoted description with quotes -> imported
    '11/11/2026 23:49:53,Sam B,sam@example.com,https://archive.org/details/rascayu-videoclip,Argentina,52,'
    '"A dark synth remix of ""You Rascal You"".\n\nSecond paragraph.",Suno for the music',
    # normal one
    '11/11/2026 23:51:40,Kim C,kim@example.com,https://archive.org/details/jcappello-bathala-teeth-2026,"Kingston, NY",Unknown,'
    'Threw a song onto some old footage,',
    # not archive.org -> skipped (no archive.org source)
    '11/15/2026 13:17:26,Lee D,lee@example.com,https://m.youtube.com/watch?v=UfqUGSa_Nf0&ra=m,Canada,58,Music from outer space,No',
    # duplicate of the row above (same item) -> skipped
    '11/15/2026 14:00:00,Sam B,sam@example.com,https://www.archive.org/details/rascayu-videoclip/,Argentina,52,again,',
    # blank row -> ignored
    ',,,,,,,',
    '11/15/2026 12:45:14,Ann E,ann@example.com,https://archive.org/details/spirit-and-opportunity,Los Angeles,50,Time lapse plants,ABSOLUTELY NO',
])

MAPPING = {"link": 3, "title": None, "description": 6}


def make_admin(app, email="admin@example.com"):
    """A test client logged in as a new admin."""
    return make_user(app, email, ["admin"])[0]


def post(client, path="/api/admin/import", **body):
    return client.post(path, json=body)


# ---- link parsing: only real archive.org items count --------------------------

@pytest.mark.parametrize("value,ident", [
    ("https://archive.org/details/rascayu-videoclip", "rascayu-videoclip"),
    ("http://archive.org/details/abc_1.2", "abc_1.2"),
    ("https://www.archive.org/details/abc/", "abc"),
    ("https://archive.org/details/abc?tab=about#x", "abc"),
    ("https://archive.org/embed/abc", "abc"),
    ("https://archive.org/download/abc/file.mp4", "abc"),
    ("archive.org/details/abc", "abc"),
    ("  https://archive.org/details/abc  ", "abc"),
])
def test_parse_archive_url_accepts_item_links(value, ident):
    assert parse_archive_url(value) == ident


@pytest.mark.parametrize("value", [
    "", None, "   ",
    "https://m.youtube.com/watch?v=UfqUGSa_Nf0",
    "https://youtu.be/abc",
    "https://archive.org.evil.com/details/abc",
    "https://notarchive.org/details/abc",
    "https://archive.org@evil.com/details/abc",
    "https://archive.org/",
    "https://archive.org/about/abc",
    "https://archive.org/details/",
    "ftp://archive.org/details/abc",
    "abc",                                   # bare identifier has no archive.org source
    "Calculation reference 336A41C34 carried out on 07 July 2026",
    "https://archive.org/details/abc and more text",
])
def test_parse_archive_url_rejects_everything_else(value):
    assert parse_archive_url(value) is None


# ---- CSV reading ------------------------------------------------------------------

def test_parse_csv_handles_multiline_cells_bom_blank_rows_and_numbering():
    headers, rows = parse_csv("﻿" + CSV_TEXT)
    assert headers[3].startswith("URL/Link")
    numbers = [n for n, _ in rows]
    assert numbers == [2, 3, 4, 5, 6, 8]            # row 7 (blank) dropped, numbering kept
    assert "Second paragraph." in rows[1][1][6]     # quoted newline stayed in one cell


def test_parse_csv_errors():
    with pytest.raises(ValueError, match="empty"):
        parse_csv("\n\n")
    with pytest.raises(ValueError, match="no data rows"):
        parse_csv("a,b\n")
    with pytest.raises(ValueError, match="too large"):
        parse_csv("a\n" + "x" * (import_service.MAX_BYTES + 1))


def test_suggest_mapping_finds_link_by_content_and_description_by_header():
    headers, rows = parse_csv(CSV_TEXT)
    m = suggest_mapping(headers, rows)
    assert m == {"link": 3, "title": None, "creator": 1, "description": 6, "public_domain_works": None,
                 "ai_disclosure": 7, "eligible": None}


def test_validate_mapping():
    assert validate_mapping({"link": 1}, 5) == {
        "link": 1, "title": None, "creator": None, "description": None, "public_domain_works": None,
        "ai_disclosure": None, "eligible": None}
    assert validate_mapping({"link": 1, "creator": 0, "eligible": 4}, 5)["eligible"] == 4
    for bad in (None, {}, {"link": 9}, {"link": "1"}, {"link": True}, {"link": 0, "title": -1},
                {"link": 0, "creator": 5}, {"link": 0, "eligible": "x"}, {"link": 0, "ai_disclosure": True}):
        with pytest.raises(ValueError):
            validate_mapping(bad, 5)


# ---- API ----------------------------------------------------------------------------

def test_import_endpoints_require_admin(app, client):
    assert post(client, "/api/admin/import/preview", csv_text=CSV_TEXT).status_code == 401
    other, _ = make_user(app, "u@example.com", ["reviewer", "judge"])
    assert post(other, "/api/admin/import/preview", csv_text=CSV_TEXT).status_code == 403
    assert post(other, csv_text=CSV_TEXT, mapping=MAPPING, on_existing="skip").status_code == 403


def test_preview_returns_headers_samples_and_suggestion(app):
    client = make_admin(app)
    d = post(client, "/api/admin/import/preview", csv_text=CSV_TEXT).get_json()
    assert d["row_count"] == 6 and len(d["sample_rows"]) == 5
    assert d["headers"][2] == "Your email"
    assert d["suggested_mapping"]["link"] == 3
    assert "collection" not in d
    assert post(client, "/api/admin/import/preview", csv_text="").status_code == 400


def test_dry_run_classifies_rows_and_writes_nothing(app):
    client = make_admin(app)
    r = post(client, csv_text=CSV_TEXT, mapping=MAPPING, dry_run=True)
    d = r.get_json()
    assert r.status_code == 200 and d["dry_run"] is True
    assert d["summary"] == {"rows": 6, "new": 3, "existing": 0, "skipped": 3, "ineligible": 0, "ineligible_in_database": 0}
    reasons = {s["row"]: s["reason"] for s in d["skipped"]}
    assert reasons == {2: "Not an archive.org item link", 5: "Not an archive.org item link", 6: "Duplicate of row 3"}
    assert [s["identifier"] for s in d["samples"]] == ["rascayu-videoclip", "jcappello-bathala-teeth-2026", "spirit-and-opportunity"]
    assert app.repos["films"].count() == 0


def test_import_adds_films(app):
    client = make_admin(app)
    r = post(client, csv_text=CSV_TEXT, mapping=MAPPING, on_existing="skip")
    assert r.status_code == 200
    assert r.get_json()["result"] == {
        "added": 3, "updated": 0, "skipped_existing": 0, "skipped_invalid": 3, "title_lookup_started": False,
    }

    row = app.db.fetchone("SELECT * FROM films WHERE ia_identifier='rascayu-videoclip'")
    assert row["in_judges_pool"] == 0
    assert row["title"] == "rascayu-videoclip"                      # no title column -> identifier
    assert row["description"] == 'A dark synth remix of "You Rascal You".\n\nSecond paragraph.'
    assert app.db.fetchone("SELECT 1 FROM films WHERE ia_identifier LIKE '%youtube%' OR ia_identifier='UfqUGSa_Nf0'") is None
    assert app.repos["films"].count() == 3

    # raters see them once they are assigned
    rev, rid = make_user(app, "rev@example.com", ["reviewer"])
    assert rev.get("/api/films/next").get_json()["code"] == "no_assignments"
    assign(app, rid, app.repos["films"].get_by_identifier("rascayu-videoclip")["id"])
    assert rev.get("/api/films/next").get_json()["identifier"] == "rascayu-videoclip"


def test_title_column_is_used_when_mapped(app):
    client = make_admin(app)
    csv_text = "Film,Link\nMy Film,https://archive.org/details/a1\n,https://archive.org/details/a2\n"
    post(client, csv_text=csv_text, mapping={"link": 1, "title": 0}, on_existing="skip")
    assert app.repos["films"].get_by_identifier("a1")["title"] == "My Film"
    assert app.repos["films"].get_by_identifier("a2")["title"] == "a2"      # blank -> identifier


def test_existing_films_skip_or_update_chosen_by_caller(app):
    client = make_admin(app)
    app.repos["films"].import_rows([{"identifier": "a1", "title": "Old title", "description": "Old desc"}], "skip")
    csv_text = "Title,Description,Link\nNew title,New desc,https://archive.org/details/a1\nB,Desc B,https://archive.org/details/b1\n"
    mp = {"link": 2, "title": 0, "description": 1}

    plan = post(client, csv_text=csv_text, mapping=mp, dry_run=True).get_json()
    assert plan["summary"]["existing"] == 1 and plan["summary"]["new"] == 1

    # the caller must say what to do about existing films
    assert post(client, csv_text=csv_text, mapping=mp).status_code == 400
    assert post(client, csv_text=csv_text, mapping=mp, on_existing="overwrite").status_code == 400

    r = post(client, csv_text=csv_text, mapping=mp, on_existing="skip").get_json()["result"]
    assert (r["added"], r["updated"], r["skipped_existing"]) == (1, 0, 1)
    assert app.repos["films"].get_by_identifier("a1")["title"] == "Old title"

    r = post(client, csv_text=csv_text, mapping=mp, on_existing="update").get_json()["result"]
    assert (r["added"], r["updated"], r["skipped_existing"]) == (0, 2, 0)
    a1 = app.repos["films"].get_by_identifier("a1")
    assert (a1["title"], a1["description"]) == ("New title", "New desc")


def test_update_never_blanks_existing_fields(app):
    client = make_admin(app)
    app.repos["films"].import_rows([{"identifier": "a1", "title": "Keep me", "description": "Keep desc"}], "skip")
    post(client, csv_text="Link\nhttps://archive.org/details/a1\n", mapping={"link": 0}, on_existing="update")
    a1 = app.repos["films"].get_by_identifier("a1")
    assert (a1["title"], a1["description"]) == ("Keep me", "Keep desc")


def test_invalid_requests(app, client):
    client = make_admin(app)
    assert post(client, csv_text=CSV_TEXT, mapping={"link": 99}, on_existing="skip").status_code == 400
    assert post(client, csv_text=CSV_TEXT, mapping={"title": 0}, on_existing="skip").status_code == 400
    assert post(client, csv_text="", mapping=MAPPING, on_existing="skip").status_code == 400
    # a mapping that finds no archive.org links at all imports nothing
    r = post(client, csv_text=CSV_TEXT, mapping={"link": 1}, on_existing="skip")
    assert r.status_code == 400 and r.get_json()["summary"]["skipped"] == 6
    assert app.repos["films"].count() == 0


# ---- title lookup (background) -----------------------------------------------------

def test_title_lookup_runs_in_background_and_never_overwrites_real_titles(app, monkeypatch):
    client = make_admin(app)
    app.repos["films"].import_rows([{"identifier": "has-title", "title": "Real title", "description": None}], "skip")
    ia = app.services["ia"]
    monkeypatch.setattr(type(ia), "fetch_title", lambda self, ident: {"a1": "Looked Up", "has-title": "Archive Title"}.get(ident))

    csv_text = "Link\nhttps://archive.org/details/a1\nhttps://archive.org/details/a2\nhttps://archive.org/details/has-title\n"
    r = post(client, csv_text=csv_text, mapping={"link": 0}, on_existing="update", lookup_titles=True)
    assert r.get_json()["result"]["title_lookup_started"] is True
    app.services["jobs"].wait(10)

    s = client.get("/api/admin/jobs/status").get_json()
    assert s["state"] == "done" and s["kind"] == "titles" and s["processed"] == 1
    films = app.repos["films"]
    assert films.get_by_identifier("a1")["title"] == "Looked Up"
    assert films.get_by_identifier("a2")["title"] == "a2"                 # not found -> stays identifier
    assert films.get_by_identifier("has-title")["title"] == "Real title"  # never clobbered


def test_no_lookup_when_every_row_has_a_title(app):
    client = make_admin(app)
    r = post(client, csv_text="T,L\nX,https://archive.org/details/a1\n", mapping={"link": 1, "title": 0},
             on_existing="skip", lookup_titles=True)
    assert r.get_json()["result"]["title_lookup_started"] is False


def test_title_lookup_reports_progress_and_blocks_concurrent_import(app, monkeypatch):
    client = make_admin(app)
    release, started = threading.Event(), threading.Event()

    def slow_titles(self, identifiers, workers=10, progress=None):
        progress("titles", 1, len(identifiers))
        started.set()
        release.wait(10)
        return {}

    monkeypatch.setattr(type(app.services["ia"]), "fetch_titles", slow_titles)
    csv_text = "Link\nhttps://archive.org/details/a1\nhttps://archive.org/details/a2\n"
    post(client, csv_text=csv_text, mapping={"link": 0}, on_existing="skip", lookup_titles=True)
    assert started.wait(10)
    s = client.get("/api/admin/jobs/status").get_json()
    assert (s["state"], s["kind"], s["phase"], s["done"], s["total"]) == ("running", "titles", "titles", 1, 2)

    assert post(client, csv_text=csv_text, mapping={"link": 0}, on_existing="skip").status_code == 409
    assert client.post("/api/admin/db/empty", json={"confirm": "EMPTY"}).status_code == 409
    release.set()
    app.services["jobs"].wait(10)


# ---- the real form's columns: creator, description, AI disclosure, public-domain works, eligible ----

FORM_HEADER = (
    "Timestamp,Your name,Your email,URL/Link to your film at archive.org,Where are you located?,Your age,"
    "Description of your film / Artist's Statement,"
    "\"If you used AI tools, please explain\","
    "Please list out each public domain item used in your film,Eligible (yes/no)"
)

FORM_CSV = "\n".join([
    FORM_HEADER,
    '1,Sam B,sam@example.com,https://archive.org/details/film-a,AR,52,"A dark synth remix.\r\nSecond line.","Suno for the music","Nosferatu (1922)\nHis Girl Friday",yes',
    '2,Kim C,kim@example.com,https://archive.org/details/film-b,NY,40,Footage and a song,,"Metropolis (1927)",YES',
    '3,Lee D,lee@example.com,https://archive.org/details/film-c,CA,33,Not allowed,No AI,Things,no',
    '4,Ann E,ann@example.com,https://archive.org/details/film-d,LA,50,Undecided,No AI,Things,',
    '5,Bo F,bo@example.com,https://archive.org/details/film-e,LA,50,Odd answer,No AI,Things,maybe',
    '6,Cy G,cy@example.com,https://archive.org/details/film-a,AR,52,Repeat of A,,,yes',
])
FORM_MAP = {"link": 3, "title": None, "creator": 1, "description": 6, "public_domain_works": 8, "ai_disclosure": 7, "eligible": 9}


def test_suggest_mapping_finds_every_form_column():
    headers, rows = parse_csv(FORM_CSV)
    assert suggest_mapping(headers, rows) == FORM_MAP


def test_suggested_columns_are_never_reused():
    headers, rows = parse_csv(FORM_CSV)
    m = suggest_mapping(headers, rows)
    used = [v for v in m.values() if v is not None]
    assert len(used) == len(set(used))


def test_parse_eligible():
    assert import_service.parse_eligible("Yes") is True and import_service.parse_eligible(" y ") is True
    assert import_service.parse_eligible("NO") is False and import_service.parse_eligible("no.") is False
    for v in ("", None, "maybe", "yes and no", "   "):
        assert import_service.parse_eligible(v) is None


def test_dry_run_skips_ineligible_blank_and_unclear_eligible_rows(app):
    client = make_admin(app)
    d = post(client, csv_text=FORM_CSV, mapping=FORM_MAP, dry_run=True).get_json()
    assert d["summary"] == {"rows": 6, "new": 2, "existing": 0, "skipped": 4, "ineligible": 1, "ineligible_in_database": 0}
    reasons = {s["row"]: s["reason"] for s in d["skipped"]}
    assert reasons == {
        4: "Not eligible (Eligible is no)",
        5: "Eligible is blank or not yes/no",
        6: "Eligible is blank or not yes/no",
        7: "Duplicate of row 2",
    }
    assert [s["identifier"] for s in d["samples"]] == ["film-a", "film-b"]
    assert d["samples"][0]["creator"] == "Sam B"
    assert app.repos["films"].count() == 0


def test_import_stores_all_the_film_fields_and_ineligible_films_are_not_loaded(app):
    client = make_admin(app)
    r = post(client, csv_text=FORM_CSV, mapping=FORM_MAP, on_existing="skip")
    assert r.status_code == 200 and r.get_json()["result"]["added"] == 2
    a = app.repos["films"].get_by_identifier("film-a")
    assert a["creator"] == "Sam B"
    assert a["description"] == "A dark synth remix.\nSecond line."
    assert a["public_domain_works"] == "Nosferatu (1922)\nHis Girl Friday"
    assert a["ai_disclosure"] == "Suno for the music"
    assert a["in_judges_pool"] == 0
    b = app.repos["films"].get_by_identifier("film-b")
    assert (b["creator"], b["ai_disclosure"], b["public_domain_works"]) == ("Kim C", None, "Metropolis (1927)")  # blank cell -> none
    for ident in ("film-c", "film-d", "film-e"):
        assert app.repos["films"].get_by_identifier(ident) is None
    assert app.repos["films"].count() == 2


def test_the_details_reach_the_reviewer(app):
    client = make_admin(app)
    post(client, csv_text=FORM_CSV, mapping=FORM_MAP, on_existing="skip")
    rev, rid = make_user(app, "rev@example.com", ["reviewer"])
    assign(app, rid, app.repos["films"].get_by_identifier("film-a")["id"])
    f = rev.get("/api/films/next").get_json()
    assert (f["creator"], f["aiDisclosure"], f["publicDomainWorks"]) == ("Sam B", "Suno for the music", "Nosferatu (1922)\nHis Girl Friday")


def test_without_an_eligible_column_every_row_counts(app):
    client = make_admin(app)
    m = {**FORM_MAP, "eligible": None}
    d = post(client, csv_text=FORM_CSV, mapping=m, dry_run=True).get_json()
    assert d["summary"]["new"] == 5 and d["summary"]["ineligible"] == 0   # only the duplicate is skipped


def test_reimport_updates_or_skips_existing_films_and_blank_cells_never_erase(app):
    client = make_admin(app)
    post(client, csv_text=FORM_CSV, mapping=FORM_MAP, on_existing="skip")
    csv2 = FORM_HEADER + "\n" + "\n".join([
        '1,Samuel B,s@example.com,https://archive.org/details/film-a,AR,52,,,,yes',     # new creator, blanks elsewhere
        '2,Kim C,k@example.com,https://archive.org/details/film-b,NY,40,Changed,Now used Suno,,yes',
        '3,New N,n@example.com,https://archive.org/details/film-f,NY,40,Another,,Rear Window,yes',
    ])
    plan = post(client, csv_text=csv2, mapping=FORM_MAP, dry_run=True).get_json()["summary"]
    assert (plan["new"], plan["existing"]) == (1, 2)
    assert post(client, csv_text=csv2, mapping=FORM_MAP).status_code == 400      # must choose skip / update
    r = post(client, csv_text=csv2, mapping=FORM_MAP, on_existing="skip").get_json()["result"]
    assert (r["added"], r["updated"], r["skipped_existing"]) == (1, 0, 2)
    assert app.repos["films"].get_by_identifier("film-a")["creator"] == "Sam B"   # skip: untouched
    r = post(client, csv_text=csv2, mapping=FORM_MAP, on_existing="update").get_json()["result"]
    assert (r["added"], r["updated"]) == (0, 3)
    a = app.repos["films"].get_by_identifier("film-a")
    assert a["creator"] == "Samuel B" and a["description"] == "A dark synth remix.\nSecond line."   # blank cells kept the old text
    assert a["ai_disclosure"] == "Suno for the music" and a["public_domain_works"].startswith("Nosferatu")
    b = app.repos["films"].get_by_identifier("film-b")
    assert (b["description"], b["ai_disclosure"], b["public_domain_works"]) == ("Changed", "Now used Suno", "Metropolis (1927)")


def test_a_film_already_loaded_is_never_removed_when_its_row_now_says_no(app):
    client = make_admin(app)
    post(client, csv_text=FORM_CSV, mapping=FORM_MAP, on_existing="skip")
    fid = app.repos["films"].get_by_identifier("film-a")["id"]
    csv2 = FORM_HEADER + "\n" + '1,Sam B,s@example.com,https://archive.org/details/film-a,AR,52,Changed,,,no'
    d = post(client, csv_text=csv2, mapping=FORM_MAP, dry_run=True).get_json()
    assert d["summary"]["ineligible"] == 1 and d["summary"]["ineligible_in_database"] == 1
    assert post(client, csv_text=csv2, mapping=FORM_MAP, on_existing="update").status_code == 400   # nothing importable
    assert app.repos["films"].get_by_identifier("film-a")["id"] == fid
    assert app.repos["films"].get_by_identifier("film-a")["description"] != "Changed"


def test_an_eligible_row_after_an_ineligible_duplicate_is_still_imported(app):
    client = make_admin(app)
    csv_text = FORM_HEADER + "\n" + "\n".join([
        '1,A,a@example.com,https://archive.org/details/dup,x,1,first,,,no',
        '2,B,b@example.com,https://archive.org/details/dup,x,1,second,,,yes',
    ])
    d = post(client, csv_text=csv_text, mapping=FORM_MAP, dry_run=True).get_json()
    assert d["summary"]["new"] == 1 and d["samples"][0]["row"] == 3
