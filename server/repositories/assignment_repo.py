import sqlite3
from typing import Optional

from ..db import Database

# Order of progress. `assigned` -> `seen` -> `rated`; a status never goes backwards.
STATUSES = ("assigned", "seen", "rated")


class AssignmentRepository:
    """Which films each person has to rate, and how far they are (assigned / seen / rated)."""

    def __init__(self, db: Database):
        self.db = db

    def add(self, user_id: int, film_id: int) -> bool:
        """Give `film_id` to `user_id`. False if they already had it."""
        conn = self.db.connect()
        try:
            with conn:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO assignments (user_id, film_id) VALUES (?, ?)",
                    (int(user_id), int(film_id)),
                )
            return cur.rowcount == 1
        finally:
            conn.close()

    def get(self, user_id: int, film_id: int) -> Optional[sqlite3.Row]:
        return self.db.fetchone(
            "SELECT user_id, film_id, status, assigned_at, seen_at, rated_at "
            "FROM assignments WHERE user_id = ? AND film_id = ?",
            (int(user_id), int(film_id)),
        )

    def count_for_user(self, user_id: int) -> int:
        row = self.db.fetchone("SELECT COUNT(1) AS n FROM assignments WHERE user_id = ?", (int(user_id),))
        return int(row["n"]) if row else 0

    def next_for_user(self, user_id: int) -> Optional[sqlite3.Row]:
        """The film to show next: one the person opened but did not finish (oldest first),
        otherwise a random one that has not been opened yet. None when nothing is left."""
        return self.db.fetchone(
            """
            SELECT f.id AS film_id, a.status
            FROM assignments a
            JOIN films f ON f.id = a.film_id
            WHERE a.user_id = ? AND a.status IN ('assigned', 'seen')
            ORDER BY (a.status = 'seen') DESC, a.seen_at ASC, RANDOM()
            LIMIT 1
            """,
            (int(user_id),),
        )

    def mark_seen(self, user_id: int, film_id: int) -> None:
        """First time a person opens a film: assigned -> seen. Does nothing otherwise."""
        conn = self.db.connect()
        try:
            with conn:
                conn.execute(
                    "UPDATE assignments SET status = 'seen', seen_at = datetime('now') "
                    "WHERE user_id = ? AND film_id = ? AND status = 'assigned'",
                    (int(user_id), int(film_id)),
                )
        finally:
            conn.close()
