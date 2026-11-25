import sqlite3
from typing import Optional
from ..db import Database

# Film fields the spreadsheet import can fill in.
_IMPORT_FIELDS = ["title", "creator", "description", "public_domain_works", "ai_disclosure"]
_FILM_COLUMNS = (
    "id, ia_identifier, title, creator, description, public_domain_works, ai_disclosure, in_judges_pool"
)


class FilmRepository:
    @staticmethod
    def _html_to_text(s: str) -> str:
        """Convert IA HTML description to plain text preserving line structure."""
        import re
        # Block-level and list tags → newline
        s = re.sub(r'<br\s*/?>', '\n', s, flags=re.IGNORECASE)
        s = re.sub(r'</div>', '\n', s, flags=re.IGNORECASE)
        s = re.sub(r'<div[^>]*>', '', s, flags=re.IGNORECASE)
        s = re.sub(r'<li[^>]*>', '\n', s, flags=re.IGNORECASE)
        s = re.sub(r'</li>', '', s, flags=re.IGNORECASE)
        s = re.sub(r'</?ul[^>]*>', '\n', s, flags=re.IGNORECASE)
        s = re.sub(r'</?ol[^>]*>', '\n', s, flags=re.IGNORECASE)
        s = re.sub(r'</?p[^>]*>', '\n', s, flags=re.IGNORECASE)
        # Strip all remaining tags (keep text content, e.g. URLs inside <a>)
        s = re.sub(r'<[^>]+>', '', s)
        # Decode common HTML entities
        entities = [('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'),
                    ('&quot;', '"'), ('&#39;', "'"), ('&nbsp;', ' ')]
        for ent, char in entities:
            s = s.replace(ent, char)
        # Replace residual non-breaking spaces with regular spaces
        s = s.replace('\xa0', ' ')
        # Lines that are now only whitespace become empty (blank lines)
        s = '\n'.join(line if line.strip() else '' for line in s.split('\n'))
        # Collapse 3+ newlines to a single blank line
        s = re.sub(r'\n{3,}', '\n\n', s)
        return s.strip()

    @staticmethod
    def _looks_like_html(s: str) -> bool:
        import re
        return bool(re.search(r'<(br|div|p|b|i|a|span)\b', s, flags=re.IGNORECASE))

    def _clean_plain_text(self, s: str) -> str:
        """Clean plain-text descriptions that use \xa0 as line-break surrogates."""
        import re
        # \xa0 \xa0 (two or more nbsp) = paragraph break
        s = re.sub(r'[ \xa0]*\xa0[ \xa0]*\xa0[ \xa0]*', '\n\n', s)
        # single \xa0 = line break
        s = re.sub(r'[ ]*\xa0[ ]*', '\n', s)
        s = re.sub(r'\n{3,}', '\n\n', s)
        return s.strip()

    def _normalize_description(self, v):
        # IA may return description as str or list; store a single text blob.
        if v is None:
            return None
        if isinstance(v, list):
            parts = [str(x) for x in v if x is not None and str(x).strip()]
            if not parts:
                return None
            joined = "\n\n".join(parts)
            v = joined
        s = str(v).strip()
        if not s:
            return None
        if self._looks_like_html(s):
            return self._html_to_text(s)
        return self._clean_plain_text(s)

    def __init__(self, db: Database):
        self.db = db

    def get_by_identifier(self, identifier: str) -> Optional[sqlite3.Row]:
        return self.db.fetchone(
            f"SELECT {_FILM_COLUMNS} FROM films WHERE ia_identifier = ?",
            (identifier,),
        )

    def get_by_id(self, film_id: int) -> Optional[sqlite3.Row]:
        return self.db.fetchone(f"SELECT {_FILM_COLUMNS} FROM films WHERE id = ?", (film_id,))

    def count(self) -> int:
        row = self.db.fetchone("SELECT COUNT(1) AS n FROM films")
        return int(row["n"]) if row else 0

    def count_in_judges_pool(self) -> int:
        row = self.db.fetchone("SELECT COUNT(1) AS n FROM films WHERE in_judges_pool = 1")
        return int(row["n"]) if row else 0

    def list_all(self) -> list[sqlite3.Row]:
        return self.db.fetchall(f"SELECT {_FILM_COLUMNS} FROM films ORDER BY id")

    def set_judges_pool(self, film_ids: list[int]) -> None:
        """Make exactly these films the judges' pool."""
        conn = self.db.connect()
        try:
            with conn:
                conn.execute("UPDATE films SET in_judges_pool = 0 WHERE in_judges_pool = 1")
                conn.executemany("UPDATE films SET in_judges_pool = 1 WHERE id = ?", [(int(i),) for i in film_ids])
        finally:
            conn.close()

    def delete_all_with_ratings(self) -> dict:
        """Delete every film plus all assignments, ratings and scores (which reference films).

        One transaction, so a failure leaves the data untouched. Users are kept.
        Returns the number of rows deleted per table.
        """
        conn = self.db.connect()
        try:
            deleted = {}
            with conn:
                for table in ("rating_scores", "ratings", "assignments", "films"):  # children first
                    deleted[table] = conn.execute(f"DELETE FROM {table}").rowcount
                # Restart the AUTOINCREMENT counters so a fresh import starts at id 1.
                conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('ratings', 'films')")
            return deleted
        finally:
            conn.close()

    def existing_identifiers(self, identifiers: list[str]) -> set[str]:
        """Subset of identifiers that already have a film."""
        found: set[str] = set()
        ids = list(identifiers)
        conn = self.db.connect()
        try:
            for i in range(0, len(ids), 500):  # stay under SQLite's bound-variable limit
                chunk = ids[i:i + 500]
                q = ",".join("?" * len(chunk))
                rows = conn.execute(
                    f"SELECT ia_identifier FROM films WHERE ia_identifier IN ({q})",
                    chunk,
                ).fetchall()
                found.update(r["ia_identifier"] for r in rows)
        finally:
            conn.close()
        return found

    def import_rows(self, rows: list[dict], on_existing: str) -> dict:
        """Insert (or update) films from a spreadsheet import in one transaction.

        Each row: {identifier, title|None, creator|None, description|None,
        public_domain_works|None, ai_disclosure|None}.
        on_existing: "skip" leaves films that already exist untouched; "update"
        overwrites the fields the row provides (a missing value never blanks out what
        is stored). New films get title = identifier when the row has no title.
        Returns {"added", "updated", "skipped_existing"}.
        """
        if on_existing not in ("skip", "update"):
            raise ValueError('on_existing must be "skip" or "update"')
        counts = {"added": 0, "updated": 0, "skipped_existing": 0}
        existing = self.existing_identifiers([r["identifier"] for r in rows])
        conn = self.db.connect()
        try:
            with conn:
                for r in rows:
                    ident = r["identifier"]
                    values = [r.get(f) for f in _IMPORT_FIELDS]
                    if ident in existing:
                        if on_existing == "skip":
                            counts["skipped_existing"] += 1
                            continue
                        sets = ", ".join(f"{f} = COALESCE(?, {f})" for f in _IMPORT_FIELDS)
                        conn.execute(
                            f"UPDATE films SET {sets}, updated_at = datetime('now') WHERE ia_identifier = ?",
                            [*values, ident],
                        )
                        counts["updated"] += 1
                    else:
                        values[_IMPORT_FIELDS.index("title")] = r.get("title") or ident
                        cols = ", ".join(_IMPORT_FIELDS)
                        marks = ", ".join("?" * len(_IMPORT_FIELDS))
                        conn.execute(
                            f"INSERT INTO films (ia_identifier, {cols}) VALUES (?, {marks})",
                            [ident, *values],
                        )
                        counts["added"] += 1
        finally:
            conn.close()
        return counts

    def update_titles(self, titles: dict[str, str]) -> int:
        """Set looked-up titles, but only where the stored title is blank or just the identifier."""
        n = 0
        conn = self.db.connect()
        try:
            with conn:
                for ident, title in titles.items():
                    n += conn.execute(
                        "UPDATE films SET title = ?, updated_at = datetime('now') "
                        "WHERE ia_identifier = ? "
                        "AND (title IS NULL OR title = '' OR title = ia_identifier)",
                        (title, ident),
                    ).rowcount
        finally:
            conn.close()
        return n
