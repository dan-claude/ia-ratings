"""CSV (spreadsheet) import of films. Sample data is invented but shaped like a real submissions sheet."""
import importlib
import json
import threading

import pytest

from server.services import import_service
from server.services.import_service import parse_archive_url, parse_csv, suggest_mapping, validate_mapping
from server.tests.helpers import register

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

MAPPING = {"link": 3, "title": None, "description": 6, "extra": []}


def make_admin(app, client, email="admin@example.com"):
    register(client, email, "pw")
    u = app.repos["users"].get_by_email(email)
    app.repos["users"].set_admin(int(u["id"]), True)


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
    assert m["link"] == 3 and m["description"] == 6 and m["title"] is None and m["extra"] == []


def test_validate_mapping():
    assert validate_mapping({"link": 1, "extra": [2, 2]}, 5) == {"link": 1, "title": None, "description": None, "extra": [2]}
    for bad in (None, {}, {"link": 9}, {"link": "1"}, {"link": True}, {"link": 0, "title": -1}, {"link": 0, "extra": [7]}):
        with pytest.raises(ValueError):
            validate_mapping(bad, 5)


# ---- API ----------------------------------------------------------------------------

def test_import_endpoints_require_admin(app, client):
    assert post(client, "/api/admin/import/preview", csv_text=CSV_TEXT).status_code == 401
    register(client, "u@example.com", "pw")
    assert post(client, "/api/admin/import/preview", csv_text=CSV_TEXT).status_code == 403
    assert post(client, csv_text=CSV_TEXT, mapping=MAPPING, on_existing="skip").status_code == 403


def test_preview_returns_headers_samples_and_suggestion(app, client):
    make_admin(app, client)
    d = post(client, "/api/admin/import/preview", csv_text=CSV_TEXT).get_json()
    assert d["row_count"] == 6 and len(d["sample_rows"]) == 5
    assert d["headers"][2] == "Your email"
    assert d["suggested_mapping"]["link"] == 3
    assert d["collection"] == app.settings.collection
    assert post(client, "/api/admin/import/preview", csv_text="").status_code == 400


def test_dry_run_classifies_rows_and_writes_nothing(app, client):
    make_admin(app, client)
    r = post(client, csv_text=CSV_TEXT, mapping=MAPPING, dry_run=True)
    d = r.get_json()
    assert r.status_code == 200 and d["dry_run"] is True
    assert d["summary"] == {"rows": 6, "new": 3, "existing": 0, "skipped": 3}
    reasons = {s["row"]: s["reason"] for s in d["skipped"]}
    assert reasons == {2: "Not an archive.org item link", 5: "Not an archive.org item link", 6: "Duplicate of row 3"}
    assert [s["identifier"] for s in d["samples"]] == ["rascayu-videoclip", "jcappello-bathala-teeth-2026", "spirit-and-opportunity"]
    assert app.repos["films"].count() == 0


def test_import_adds_films_to_the_configured_collection(app, client):
    make_admin(app, client)
    r = post(client, csv_text=CSV_TEXT, mapping=MAPPING, on_existing="skip")
    assert r.status_code == 200
    assert r.get_json()["result"] == {"added": 3, "updated": 0, "skipped_existing": 0, "skipped_invalid": 3, "title_lookup_started": False}

    row = app.db.fetchone("SELECT * FROM films WHERE ia_identifier='rascayu-videoclip'")
    assert row["collection"] == app.settings.collection and row["mediatype"] == "movies"
    assert row["title"] == "rascayu-videoclip"                      # no title column -> identifier
    assert row["description"] == 'A dark synth remix of "You Rascal You".\n\nSecond paragraph.'
    assert app.db.fetchone("SELECT 1 FROM films WHERE ia_identifier LIKE '%youtube%' OR ia_identifier='UfqUGSa_Nf0'") is None
    assert app.repos["films"].count() == 3

    f = client.get("/api/films/next").get_json()          # raters can now rate them
    assert f["identifier"] in {"rascayu-videoclip", "jcappello-bathala-teeth-2026", "spirit-and-opportunity"}


def test_title_column_is_used_when_mapped(app, client):
    make_admin(app, client)
    csv_text = "Film,Link\nMy Film,https://archive.org/details/a1\n,https://archive.org/details/a2\n"
    post(client, csv_text=csv_text, mapping={"link": 1, "title": 0}, on_existing="skip")
    assert app.repos["films"].get_by_identifier("a1")["title"] == "My Film"
    assert app.repos["films"].get_by_identifier("a2")["title"] == "a2"      # blank -> identifier


def test_existing_films_skip_or_update_chosen_by_caller(app, client):
    make_admin(app, client)
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


def test_update_never_blanks_existing_fields(app, client):
    make_admin(app, client)
    app.repos["films"].import_rows([{"identifier": "a1", "title": "Keep me", "description": "Keep desc"}], "skip")
    post(client, csv_text="Link\nhttps://archive.org/details/a1\n", mapping={"link": 0}, on_existing="update")
    a1 = app.repos["films"].get_by_identifier("a1")
    assert (a1["title"], a1["description"]) == ("Keep me", "Keep desc")


def test_extra_columns_stored_admin_side_only(app, client):
    make_admin(app, client)
    post(client, csv_text=CSV_TEXT, mapping={**MAPPING, "extra": [7]}, on_existing="skip")
    meta = json.loads(app.db.fetchone("SELECT metadata_json m FROM films WHERE ia_identifier='rascayu-videoclip'")["m"])
    assert meta == {"source": "csv_import", "columns": {"AI tools used": "Suno for the music"}}
    # a film with an empty extra cell has no extras, and nothing leaks to raters
    f = client.get("/api/films/next").get_json()
    assert set(f) == {"identifier", "title", "description", "embedUrl"}
    assert "Suno" not in json.dumps(f)


def test_invalid_requests(app, client):
    make_admin(app, client)
    assert post(client, csv_text=CSV_TEXT, mapping={"link": 99}, on_existing="skip").status_code == 400
    assert post(client, csv_text=CSV_TEXT, mapping={"title": 0}, on_existing="skip").status_code == 400
    assert post(client, csv_text="", mapping=MAPPING, on_existing="skip").status_code == 400
    # a mapping that finds no archive.org links at all imports nothing
    r = post(client, csv_text=CSV_TEXT, mapping={"link": 1}, on_existing="skip")
    assert r.status_code == 400 and r.get_json()["summary"]["skipped"] == 6
    assert app.repos["films"].count() == 0


# ---- title lookup (background) -----------------------------------------------------

def test_title_lookup_runs_in_background_and_never_overwrites_real_titles(app, client, monkeypatch):
    make_admin(app, client)
    app.repos["films"].import_rows([{"identifier": "has-title", "title": "Real title", "description": None}], "skip")
    ia = app.services["ia"]
    monkeypatch.setattr(type(ia), "fetch_title", lambda self, ident: {"a1": "Looked Up", "has-title": "Archive Title"}.get(ident))

    csv_text = "Link\nhttps://archive.org/details/a1\nhttps://archive.org/details/a2\nhttps://archive.org/details/has-title\n"
    r = post(client, csv_text=csv_text, mapping={"link": 0}, on_existing="update", lookup_titles=True)
    assert r.get_json()["result"]["title_lookup_started"] is True
    app.services["sync"].wait(10)

    s = client.get("/api/admin/sync/status").get_json()
    assert s["state"] == "done" and s["kind"] == "titles" and s["synced"] == 1
    films = app.repos["films"]
    assert films.get_by_identifier("a1")["title"] == "Looked Up"
    assert films.get_by_identifier("a2")["title"] == "a2"                 # not found -> stays identifier
    assert films.get_by_identifier("has-title")["title"] == "Real title"  # never clobbered


def test_no_lookup_when_every_row_has_a_title(app, client):
    make_admin(app, client)
    r = post(client, csv_text="T,L\nX,https://archive.org/details/a1\n", mapping={"link": 1, "title": 0},
             on_existing="skip", lookup_titles=True)
    assert r.get_json()["result"]["title_lookup_started"] is False


def test_title_lookup_reports_progress_and_blocks_concurrent_import(app, client, monkeypatch):
    make_admin(app, client)
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
    s = client.get("/api/admin/sync/status").get_json()
    assert (s["state"], s["kind"], s["phase"], s["done"], s["total"]) == ("running", "titles", "titles", 1, 2)

    assert post(client, csv_text=csv_text, mapping={"link": 0}, on_existing="skip").status_code == 409
    assert client.post("/api/admin/sync").status_code == 409
    assert client.post("/api/admin/db/empty", json={"confirm": "EMPTY"}).status_code == 409
    release.set()
    app.services["sync"].wait(10)


def test_sync_status_reports_kind(app, client, monkeypatch):
    make_admin(app, client)
    monkeypatch.setattr(type(app.services["ia"]), "sync_collection", lambda self, f, progress=None, **k: 0)
    client.post("/api/admin/sync")
    app.services["sync"].wait(10)
    assert client.get("/api/admin/sync/status").get_json()["kind"] == "sync"


# ---- configurable collection --------------------------------------------------------

def test_collection_is_configurable_via_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "c.db"))
    monkeypatch.setenv("SESSION_SECRET", "s")
    monkeypatch.setenv("AUTH_SCHEME", "local")
    monkeypatch.setenv("IA_COLLECTION", "2027-public-domain-day-film-contest")
    import server.app as app_module
    importlib.reload(app_module)
    app = app_module.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    assert app.settings.collection == "2027-public-domain-day-film-contest"
    assert app.services["ia"].collection == "2027-public-domain-day-film-contest"
    make_admin(app, client)
    post(client, csv_text="Link\nhttps://archive.org/details/a1\n", mapping={"link": 0}, on_existing="skip")
    assert app.db.fetchone("SELECT collection c FROM films")["c"] == "2027-public-domain-day-film-contest"
    assert client.get("/api/films/next").status_code == 200

    # films from another collection are not offered to raters
    app.db.connect().execute("UPDATE films SET collection='other'").connection.commit()
    assert client.get("/api/films/next").get_json()["code"] == "no_films"


def test_default_collection_unchanged(app):
    assert app.settings.collection == "2026-public-domain-day-film-contest"
