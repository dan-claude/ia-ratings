import sqlite3

from ..db import Database


def author_name(row) -> str:
    """The name shown for a note's author: archive.org username, else GitHub username,
    else the part of the email before the "@".

    Never an email address: an `ia_username` can be one (older accounts were keyed on
    whatever was typed at login), and judges must not see each other's addresses.
    """
    for key in ("ia_username", "github_username", "email"):
        value = (row[key] or "").strip()
        local = value.split("@", 1)[0].strip()
        if local:
            return local
    return "unknown"


class NoteRepository:
    """Judges' free-text notes about films (many per film)."""

    def __init__(self, db: Database):
        self.db = db

    def list_for_film(self, film_id: int) -> list[sqlite3.Row]:
        """Notes for a film, oldest first. Use `author_name(row)` for the writer's display name."""
        return self.db.fetchall(
            """
            SELECT n.id, n.body, n.created_at,
                   u.ia_username, u.github_username, u.email
            FROM film_notes n JOIN users u ON u.id = n.user_id
            WHERE n.film_id = ?
            ORDER BY n.created_at, n.id
            """,
            (int(film_id),),
        )

    def list_for_export(self, collection: str) -> list[sqlite3.Row]:
        """Every note on films in `collection`, grouped by film, oldest first within a film."""
        return self.db.fetchall(
            """
            SELECT n.created_at, f.ia_identifier AS identifier, f.title AS title, n.body,
                   u.ia_username, u.github_username, u.email
            FROM film_notes n
            JOIN films f ON f.id = n.film_id
            JOIN users u ON u.id = n.user_id
            WHERE f.collection = ?
            ORDER BY f.ia_identifier, n.created_at, n.id
            """,
            (collection,),
        )

    def add(self, film_id: int, user_id: int, body: str) -> sqlite3.Row:
        conn = self.db.connect()
        try:
            with conn:
                cur = conn.execute(
                    "INSERT INTO film_notes (film_id, user_id, body) VALUES (?, ?, ?)",
                    (int(film_id), int(user_id), body),
                )
                return conn.execute(
                    """
                    SELECT n.id, n.body, n.created_at,
                           u.ia_username, u.github_username, u.email
                    FROM film_notes n JOIN users u ON u.id = n.user_id
                    WHERE n.id = ?
                    """,
                    (cur.lastrowid,),
                ).fetchone()
        finally:
            conn.close()
