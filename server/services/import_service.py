"""Populate the film database from a spreadsheet exported as CSV.

The admin picks which spreadsheet column holds what (see `mapping` below). Only
rows whose link points at an archive.org item are imported: the film is played
from archive.org, so a YouTube link, a bare title or free text is skipped (and
reported) rather than creating a film that can't be shown.

mapping = {
    "link":        <column index>,          # required: an archive.org item URL
    "title":       <column index> | None,   # optional; blank -> looked up / identifier
    "description": <column index> | None,   # optional
    "extra":       [<column index>, ...],   # optional: kept in films.metadata_json (admin-only)
}
Columns are addressed by index (not header text) so duplicate/blank headers work.
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
    """Guess a mapping: the link column is the one whose cells most often are archive.org links."""
    best, best_n = None, 0
    for i in range(len(headers)):
        n = sum(1 for _, cells in rows if i < len(cells) and parse_archive_url(cells[i]))
        if n > best_n:
            best, best_n = i, n

    def find(pattern: str, skip: Optional[int]) -> Optional[int]:
        rx = re.compile(pattern, re.IGNORECASE)
        for i, h in enumerate(headers):
            if i != skip and rx.search(h):
                return i
        return None

    return {
        "link": best,
        "title": find(r"\btitle\b", best),
        "description": find(r"description|statement|synopsis|summary", best),
        "extra": [],
    }


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

    extra = mapping.get("extra") or []
    if not isinstance(extra, list) or any(isinstance(x, bool) or not isinstance(x, int) or not 0 <= x < ncols for x in extra):
        raise ValueError("Invalid extra columns")
    return {
        "link": col("link", required=True),
        "title": col("title"),
        "description": col("description"),
        "extra": list(dict.fromkeys(extra)),
    }


class ImportService:
    def __init__(self, films, ia, sync):
        self.films = films
        self.ia = ia
        self.sync = sync

    # -- planning -----------------------------------------------------------

    def build_plan(self, headers, rows, mapping, collection: str | None = None) -> list[dict]:
        """Classify every row: importable (new/existing) or skipped with a reason.

        "existing" means the film is already in `collection` (the import target;
        default: the active collection) — the same item in another collection is new.
        """
        def cell(cells, idx):
            return cells[idx].strip() if idx is not None and idx < len(cells) else ""

        items, first_row_for = [], {}
        for rownum, cells in rows:
            link = cell(cells, mapping["link"])
            ident = parse_archive_url(link)
            item = {"row": rownum, "identifier": ident, "skip": None}
            if not link:
                item["skip"] = "No link"
            elif not ident:
                item["skip"] = "Not an archive.org item link"
            elif ident in first_row_for:
                item["skip"] = f"Duplicate of row {first_row_for[ident]}"
            if item["skip"]:
                items.append(item)
                continue
            first_row_for[ident] = rownum
            item["title"] = cell(cells, mapping["title"]) or None
            item["description"] = (
                self.films._normalize_description(cell(cells, mapping["description"])) or None
            )
            extras = {headers[i] or f"column {i + 1}": cells[i].strip()
                      for i in mapping["extra"] if i < len(cells) and cells[i].strip()}
            item["metadata"] = {"source": "csv_import", "columns": extras} if mapping["extra"] else None
            items.append(item)

        existing = self.films.existing_identifiers([i["identifier"] for i in items if not i["skip"]], collection)
        for i in items:
            i["exists"] = (not i["skip"]) and i["identifier"] in existing
        return items

    @staticmethod
    def summarize(items: list[dict]) -> dict:
        ok = [i for i in items if not i["skip"]]
        return {
            "rows": len(items),
            "new": sum(1 for i in ok if not i["exists"]),
            "existing": sum(1 for i in ok if i["exists"]),
            "skipped": len(items) - len(ok),
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
                "description": desc[:200] + ("…" if len(desc) > 200 else ""),
                "exists": i["exists"],
            })
            if len(out) >= limit:
                break
        return out

    # -- doing it -----------------------------------------------------------

    def run(self, items: list[dict], on_existing: str, lookup_titles: bool, collection: str | None = None) -> dict:
        ok = [i for i in items if not i["skip"]]
        counts = self.films.import_rows(ok, on_existing, collection)
        lookup_started = False
        if lookup_titles:
            # Rows that gave no title; update_titles never overwrites a real title.
            ids = [i["identifier"] for i in ok
                   if not i["title"] and not (i["exists"] and on_existing == "skip")]
            if ids:
                lookup_started = self.sync.start_job(
                    "titles", lambda progress: self._lookup_titles(ids, progress, collection))
        return {**counts, "skipped_invalid": len(items) - len(ok), "title_lookup_started": lookup_started}

    def _lookup_titles(self, identifiers: list[str], progress, collection: str | None = None) -> int:
        titles = self.ia.fetch_titles(identifiers, progress=progress)
        return self.films.update_titles(titles, collection)
