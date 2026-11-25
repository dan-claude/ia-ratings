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

    def count(self) -> int:
        row = self.db.fetchone("SELECT COUNT(1) AS n FROM assignments")
        return int(row["n"]) if row else 0

    def add_many(self, pairs: list[tuple[int, int]]) -> int:
        """Give many (user_id, film_id) pairs in one transaction. Returns how many were new."""
        conn = self.db.connect()
        try:
            with conn:
                before = conn.total_changes
                conn.executemany(
                    "INSERT OR IGNORE INTO assignments (user_id, film_id) VALUES (?, ?)",
                    [(int(u), int(f)) for u, f in pairs],
                )
                return conn.total_changes - before
        finally:
            conn.close()

    def remove_unrated(self, user_id: int, film_id: int) -> str:
        """Take a film off a person's list. Returns "removed", "missing", or "rated" (a submitted
        rating is final, so its assignment stays)."""
        conn = self.db.connect()
        try:
            with conn:
                row = conn.execute(
                    "SELECT status FROM assignments WHERE user_id = ? AND film_id = ?", (int(user_id), int(film_id))
                ).fetchone()
                if row is None:
                    return "missing"
                if row["status"] == "rated":
                    return "rated"
                conn.execute("DELETE FROM assignments WHERE user_id = ? AND film_id = ?", (int(user_id), int(film_id)))
                return "removed"
        finally:
            conn.close()

    def reset_all(self) -> dict:
        """Start the reviewing round over: delete every assignment AND every rating and score
        (a rating without its assignment would block handing the film out again), and take all
        films out of the judges' pool. One transaction. Returns the rows deleted per table."""
        conn = self.db.connect()
        try:
            with conn:
                deleted = {t: conn.execute(f"DELETE FROM {t}").rowcount for t in ("rating_scores", "ratings", "assignments")}
                deleted["judges_pool_cleared"] = conn.execute("UPDATE films SET in_judges_pool = 0 WHERE in_judges_pool = 1").rowcount
                conn.execute("DELETE FROM sqlite_sequence WHERE name = 'ratings'")
            return deleted
        finally:
            conn.close()

    def list_with_people(self) -> list[sqlite3.Row]:
        """Every assignment with the person's email and the film's identifier (for progress views)."""
        return self.db.fetchall(
            """
            SELECT a.user_id, u.email, a.film_id, f.ia_identifier, a.status
            FROM assignments a
            JOIN users u ON u.id = a.user_id
            JOIN films f ON f.id = a.film_id
            ORDER BY f.id, u.email
            """
        )
