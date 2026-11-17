import sqlite3
from typing import Optional
from ..db import Database

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

    def __init__(self, db: Database, collection: str):
        self.db = db
        self.collection = collection

    def upsert_many_from_ia(self, docs: list[dict]) -> int:
        conn = self.db.connect()
        try:
            total = 0
            for d in docs:
                ident = d.get("identifier")
                if not ident:
                    continue
                conn.execute(
                    """
                    INSERT INTO films (ia_identifier, title, description, collection, mediatype, metadata_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, NULL, datetime('now'))
                    ON CONFLICT(ia_identifier) DO UPDATE SET
                      title=excluded.title,
                      description=excluded.description,
                      collection=excluded.collection,
                      mediatype=excluded.mediatype,
                      updated_at=datetime('now')
                    """,
                    (ident, d.get("title"), self._normalize_description(d.get("description")), self.collection, "movies"),
                )
                total += 1
            conn.commit()
            return total
        finally:
            conn.close()

    def get_by_identifier(self, identifier: str) -> Optional[sqlite3.Row]:
        return self.db.fetchone(
            "SELECT id, ia_identifier, title, description FROM films WHERE ia_identifier = ?",
            (identifier,),
        )

    def get_next_unrated_for_user(self, user_id: int) -> Optional[sqlite3.Row]:
        return self.db.fetchone(
            """
            SELECT f.ia_identifier, f.title, f.description
            FROM films f
            WHERE f.collection = ?
              AND NOT EXISTS (
                SELECT 1 FROM ratings r
                WHERE r.user_id = ?
                  AND r.film_id = f.id
              )
            ORDER BY RANDOM()
            LIMIT 1
            """,
            (self.collection, user_id),
        )

    def count(self) -> int:
        row = self.db.fetchone("SELECT COUNT(1) AS n FROM films WHERE collection = ?", (self.collection,))
        return int(row["n"]) if row else 0

    def delete_all_with_ratings(self) -> dict:
        """Delete every film plus all ratings and scores (which reference films).

        One transaction, so a failure leaves the data untouched. Users and
        criteria are kept. Returns the number of rows deleted per table.
        """
        conn = self.db.connect()
        try:
            deleted = {}
            with conn:
                for table in ("rating_scores", "ratings", "films"):  # children first
                    deleted[table] = conn.execute(f"DELETE FROM {table}").rowcount
                # Restart the AUTOINCREMENT counters so a fresh sync starts at id 1.
                conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('ratings', 'films')")
            return deleted
        finally:
            conn.close()

    def list_all_in_collection(self) -> list[sqlite3.Row]:
        return self.db.fetchall(
            "SELECT id, ia_identifier as identifier, title, description FROM films WHERE collection=? ORDER BY id",
            (self.collection,),
        )

    def get_identifiers_without_description(self, identifiers: list[str]) -> set[str]:
        """Return the subset of identifiers that have no description stored yet.

        Films that aren't in the database at all count as "without": on a first
        sync (e.g. after emptying the database) every film needs its full
        description fetched.
        """
        if not identifiers:
            return set()
        conn = self.db.connect()
        try:
            placeholders = ",".join("?" * len(identifiers))
            rows = conn.execute(
                f"SELECT ia_identifier FROM films WHERE ia_identifier IN ({placeholders})"
                f" AND description IS NOT NULL AND description != ''",
                identifiers,
            ).fetchall()
            return set(identifiers) - {r["ia_identifier"] for r in rows}
        finally:
            conn.close()
