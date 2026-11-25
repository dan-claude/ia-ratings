"""Populate the film database from a spreadsheet exported as CSV.

The admin picks which spreadsheet column holds what (see `mapping` below). Only
rows whose link points at an archive.org item are imported: the film is played
from archive.org, so a YouTube link, a bare title or free text is skipped (and
reported) rather than creating a film that can't be shown.

mapping = {
    "link":                <column index>,          # required: an archive.org item URL
    "title":               <column index> | None,   # optional; blank -> looked up / identifier
    "creator":             <column index> | None,   # optional: the "by" credit
    "description":         <column index> | None,   # optional
    "public_domain_works": <column index> | None,   # optional: list of public-domain works used
    "ai_disclosure":       <column index> | None,   # optional
    "eligible":            <column index> | None,   # optional yes/no column
}
Columns are addressed by index (not header text) so duplicate/blank headers work.

Eligibility: when an `eligible` column is mapped, only rows saying "yes" are imported.
"no" rows are skipped as not eligible; blank or unclear cells are skipped too (and
reported) rather than guessed at. Without an `eligible` column every row counts as
eligible. A film that is already in the database is never deleted by an import, even
if its row now says "no" (that is reported as a warning).
"""
import csv
import io
import re
from typing import Optional
from urllib.parse import urlsplit

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 5000

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")
_ARCHIVE_HOSTS = {"archive.org", "www.archive.org"}
_ITEM_PATHS = {"details", "embed", "download"}

# Mapping fields in display order; "link" is the only required one.
MAPPING_FIELDS = ["link", "title", "creator", "description", "public_domain_works", "ai_disclosure", "eligible"]
_YES = {"yes", "y", "true", "1"}
_NO = {"no", "n", "false", "0"}


def parse_eligible(value: Optional[str]) -> Optional[bool]:
    """True for yes, False for no, None for blank or anything else."""
    v = (value or "").strip().lower().rstrip(".!")
    if v in _YES:
        return True
    if v in _NO:
        return False
    return None


def clean_text(value: Optional[str]) -> Optional[str]:
    """Plain text from a spreadsheet cell: uniform newlines, no non-breaking spaces, trimmed; None if empty."""
    v = (value or "").replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ").strip()
    return v or None


def parse_archive_url(value: Optional[str]) -> Optional[str]:
    """Return the item identifier from an archive.org item URL, else None.

    Accepts https://archive.org/details/<id> (also /embed/<id>, /download/<id>,
    http, www, no scheme, trailing path/query). The host must be exactly
    archive.org / www.archive.org; anything else (YouTube, lookalike domains,
    bare identifiers, free text) returns None.
    """
    v = (value or "").strip()
    if not v or any(c.isspace() for c in v):
        return None
    if "://" not in v:
        v = "https://" + v
    try:
        u = urlsplit(v)
    except ValueError:
        return None
    if u.scheme not in ("http", "https") or (u.hostname or "").lower() not in _ARCHIVE_HOSTS:
        return None
    parts = [p for p in u.path.split("/") if p]
    if len(parts) < 2 or parts[0] not in _ITEM_PATHS:
        return None
    return parts[1] if _ID_RE.match(parts[1]) else None


def parse_csv(text: str) -> tuple[list[str], list[tuple[int, list[str]]]]:
    """Parse CSV text into (headers, [(row_number, cells)]).

    row_number is the spreadsheet row (header = 1), so messages match what the
    admin sees. Fully blank rows are dropped; short rows are padded.
    """
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError(f"File is too large (maximum {MAX_BYTES // (1024 * 1024)} MB)")
    text = text.lstrip("﻿")
    try:
        records = list(csv.reader(io.StringIO(text, newline="")))
    except csv.Error as exc:
        raise ValueError(f"Could not read the CSV: {exc}") from exc
    numbered = [(i + 1, r) for i, r in enumerate(records) if any(c.strip() for c in r)]
    if not numbered:
        raise ValueError("The file is empty")
    _, header_cells = numbered[0]
    headers = [h.strip() for h in header_cells]
    width = len(headers)
    rows = [(n, (cells + [""] * width)[: max(width, len(cells))]) for n, cells in numbered[1:]]
    if not rows:
        raise ValueError("The file has a header row but no data rows")
    if len(rows) > MAX_ROWS:
        raise ValueError(f"Too many rows (maximum {MAX_ROWS})")
    return headers, rows


def suggest_mapping(headers: list[str], rows: list[tuple[int, list[str]]]) -> dict:
    """Guess a mapping. The link column is the one whose cells most often are archive.org links;
    the others are found from header names, each column used at most once."""
    best, best_n = None, 0
    for i in range(len(headers)):
        n = sum(1 for _, cells in rows if i < len(cells) and parse_archive_url(cells[i]))
        if n > best_n:
            best, best_n = i, n

    used = {best} if best is not None else set()

    def find(pattern: str) -> Optional[int]:
        rx = re.compile(pattern, re.IGNORECASE)
        for i, h in enumerate(headers):
            if i not in used and rx.search(h):
                used.add(i)
                return i
        return None

    # Order matters: the longer, more specific headers claim their column first.
    mapping = {"link": best}
    mapping["eligible"] = find(r"\beligib")
    mapping["public_domain_works"] = find(r"public[ -]domain|items? used")
    mapping["ai_disclosure"] = find(r"\bAI\b|artificial intelligence")
    mapping["description"] = find(r"description|statement|synopsis|summary")
    mapping["creator"] = find(r"your name|creator|film ?maker|director|\bby\b")
    mapping["title"] = find(r"\btitle\b")
    return {k: mapping[k] for k in MAPPING_FIELDS}


def validate_mapping(mapping, ncols: int) -> dict:
    """Return a cleaned mapping or raise ValueError with a message for the admin."""
    if not isinstance(mapping, dict):
        raise ValueError("mapping is required")

    def col(name: str, required: bool = False) -> Optional[int]:
        v = mapping.get(name)
        if v is None or v == "":
            if required:
                raise ValueError(f"Choose which column holds the {name}")
            return None
        if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v < ncols:
            raise ValueError(f"Invalid column for {name}")
        return v

    return {name: col(name, required=(name == "link")) for name in MAPPING_FIELDS}


class ImportService:
    def __init__(self, films, ia, jobs):
        self.films = films
        self.ia = ia
        self.jobs = jobs

    # -- planning -----------------------------------------------------------

    def build_plan(self, headers, rows, mapping) -> list[dict]:
        """Classify every row: importable (new/existing) or skipped with a reason."""
        def cell(cells, idx):
            return cells[idx].strip() if idx is not None and idx < len(cells) else ""

        items, first_row_for = [], {}
        for rownum, cells in rows:
            link = cell(cells, mapping["link"])
            ident = parse_archive_url(link)
            item = {"row": rownum, "identifier": ident, "skip": None, "ineligible": False}
            if not link:
                item["skip"] = "No link"
            elif not ident:
                item["skip"] = "Not an archive.org item link"
            elif mapping.get("eligible") is not None:
                verdict = parse_eligible(cell(cells, mapping["eligible"]))
                if verdict is False:
                    item["skip"], item["ineligible"] = "Not eligible (Eligible is no)", True
                elif verdict is None:
                    item["skip"] = "Eligible is blank or not yes/no"
            if not item["skip"] and ident in first_row_for:
                item["skip"] = f"Duplicate of row {first_row_for[ident]}"
            if item["skip"]:
                items.append(item)
                continue
            first_row_for[ident] = rownum
            item["title"] = cell(cells, mapping["title"]) or None
            item["creator"] = clean_text(cell(cells, mapping.get("creator")))
            item["description"] = (
                self.films._normalize_description(clean_text(cell(cells, mapping["description"]))) or None
            )
            item["public_domain_works"] = clean_text(cell(cells, mapping.get("public_domain_works")))
            item["ai_disclosure"] = clean_text(cell(cells, mapping.get("ai_disclosure")))
            items.append(item)

        wanted = [i["identifier"] for i in items if i["identifier"] and (not i["skip"] or i["ineligible"])]
        existing = self.films.existing_identifiers(wanted)
        for i in items:
            i["exists"] = (not i["skip"]) and i["identifier"] in existing
            # A "no" row for a film that is already loaded: the import leaves it alone (never deletes).
            i["ineligible_in_database"] = i["ineligible"] and i["identifier"] in existing
        return items

    @staticmethod
    def summarize(items: list[dict]) -> dict:
        ok = [i for i in items if not i["skip"]]
        return {
            "rows": len(items),
            "new": sum(1 for i in ok if not i["exists"]),
            "existing": sum(1 for i in ok if i["exists"]),
            "skipped": len(items) - len(ok),
            "ineligible": sum(1 for i in items if i["ineligible"]),
            "ineligible_in_database": sum(1 for i in items if i["ineligible_in_database"]),
        }

    @staticmethod
    def skipped_rows(items: list[dict], limit: int = 100) -> list[dict]:
        return [{"row": i["row"], "reason": i["skip"]} for i in items if i["skip"]][:limit]

    @staticmethod
    def samples(items: list[dict], limit: int = 5) -> list[dict]:
        out = []
        for i in items:
            if i["skip"]:
                continue
            desc = i["description"] or ""
            out.append({
                "row": i["row"],
                "identifier": i["identifier"],
                "title": i["title"],            # None -> will be looked up / identifier
                "creator": i["creator"],
                "description": desc[:200] + ("…" if len(desc) > 200 else ""),
                "exists": i["exists"],
            })
            if len(out) >= limit:
                break
        return out

    # -- doing it -----------------------------------------------------------

    def run(self, items: list[dict], on_existing: str, lookup_titles: bool) -> dict:
        ok = [i for i in items if not i["skip"]]
        counts = self.films.import_rows(ok, on_existing)
        lookup_started = False
        if lookup_titles:
            # Rows that gave no title; update_titles never overwrites a real title.
            ids = [i["identifier"] for i in ok
                   if not i["title"] and not (i["exists"] and on_existing == "skip")]
            if ids:
                lookup_started = self.jobs.start_job(
                    "titles", lambda progress: self._lookup_titles(ids, progress))
        return {**counts, "skipped_invalid": len(items) - len(ok), "title_lookup_started": lookup_started}

    def _lookup_titles(self, identifiers: list[str], progress) -> int:
        titles = self.ia.fetch_titles(identifiers, progress=progress)
        return self.films.update_titles(titles)
