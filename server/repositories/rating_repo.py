import sqlite3
from typing import Optional

from ..db import Database


class AlreadyRated(Exception):
    """The person has already submitted this film (ratings are final)."""


class RatingRepository:
    def __init__(self, db: Database):
        self.db = db

    def submit(self, user_id: int, film_id: int, scores: dict[str, int], comment: str) -> int:
        """Record a person's final rating for a film and mark their assignment `rated`.

        The rating row, its scores and the status change are one transaction, so a
        crash can't leave half of it. Returns the rating id.
        Raises LookupError if the film isn't assigned to the person and AlreadyRated
        if they have already submitted it.
        """
        conn = self.db.connect()
        try:
            # IMMEDIATE: take the write lock first so two submits for one film can't interleave.
            conn.execute("BEGIN IMMEDIATE")
            try:
                a = conn.execute(
                    "SELECT status FROM assignments WHERE user_id = ? AND film_id = ?",
                    (user_id, film_id),
                ).fetchone()
                if a is None:
                    raise LookupError("This film is not assigned to you")
                if a["status"] == "rated":
                    raise AlreadyRated()
                cur = conn.execute(
                    "INSERT INTO ratings (user_id, film_id, comment) VALUES (?, ?, ?)",
                    (user_id, film_id, comment),
                )
                rating_id = int(cur.lastrowid)
                conn.executemany(
                    "INSERT INTO rating_scores (rating_id, category, score) VALUES (?, ?, ?)",
                    [(rating_id, key, n) for key, n in scores.items()],
                )
                conn.execute(
                    "UPDATE assignments SET status = 'rated', rated_at = datetime('now'), "
                    "seen_at = COALESCE(seen_at, datetime('now')) WHERE user_id = ? AND film_id = ?",
                    (user_id, film_id),
                )
                conn.commit()
                return rating_id
            except sqlite3.IntegrityError as exc:  # a rating row already exists
                conn.rollback()
                raise AlreadyRated() from exc
            except BaseException:
                conn.rollback()
                raise
        finally:
            conn.close()

    def get_for_user_film(self, user_id: int, film_id: int) -> Optional[dict]:
        """The person's submitted rating of a film: {"scores": {key: n}, "comment": str}, or None."""
        row = self.db.fetchone(
            "SELECT id, comment FROM ratings WHERE user_id = ? AND film_id = ?", (user_id, film_id)
        )
        if not row:
            return None
        scores = self.db.fetchall("SELECT category, score FROM rating_scores WHERE rating_id = ?", (row["id"],))
        return {"scores": {r["category"]: int(r["score"]) for r in scores}, "comment": row["comment"]}

    def list_for_export(self) -> list[dict]:
        """Every submitted rating, newest first: who, which film, scores by category, comment."""
        rows = self.db.fetchall(
            """
            SELECT r.id AS rating_id, r.created_at, r.comment, u.email AS user_email,
                   f.ia_identifier AS identifier, f.title AS title
            FROM ratings r
            JOIN users u ON u.id = r.user_id
            JOIN films f ON f.id = r.film_id
            ORDER BY r.created_at DESC, r.id DESC
            """
        )
        scores: dict[int, dict[str, int]] = {}
        for s in self.db.fetchall("SELECT rating_id, category, score FROM rating_scores"):
            scores.setdefault(int(s["rating_id"]), {})[s["category"]] = int(s["score"])
        return [{**{k: r[k] for k in r.keys()}, "scores": scores.get(int(r["rating_id"]), {})} for r in rows]
