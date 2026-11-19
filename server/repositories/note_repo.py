import sqlite3

from ..db import Database


class NoteRepository:
    """Judges' free-text notes about films (many per film)."""

    def __init__(self, db: Database):
        self.db = db

    def list_for_film(self, film_id: int) -> list[sqlite3.Row]:
        """Notes for a film, oldest first. `author` is the writer's best display name."""
        return self.db.fetchall(
            """
            SELECT n.id, n.body, n.created_at,
                   COALESCE(u.ia_username, u.github_username, u.email) AS author
            FROM film_notes n JOIN users u ON u.id = n.user_id
            WHERE n.film_id = ?
            ORDER BY n.created_at, n.id
            """,
            (int(film_id),),
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
                           COALESCE(u.ia_username, u.github_username, u.email) AS author
                    FROM film_notes n JOIN users u ON u.id = n.user_id
                    WHERE n.id = ?
                    """,
                    (cur.lastrowid,),
                ).fetchone()
        finally:
            conn.close()
