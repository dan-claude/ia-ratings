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

    def list_for_user_in_pool(self, user_id: int) -> list[dict]:
        """One person's own submitted ratings of the films in the judges' pool (whichever round
        they rated them in): film details, scores by category and the comment."""
        rows = self.db.fetchall(
            """
            SELECT r.id AS rating_id, r.comment, f.ia_identifier AS identifier, f.title AS title, f.creator AS creator,
                   COALESCE(a.round, 'reviewers') AS round
            FROM ratings r
            JOIN films f ON f.id = r.film_id AND f.in_judges_pool = 1
            LEFT JOIN assignments a ON a.user_id = r.user_id AND a.film_id = r.film_id
            WHERE r.user_id = ?
            """,
            (int(user_id),),
        )
        scores: dict[int, dict[str, int]] = {}
        for s in self.db.fetchall(
            "SELECT s.rating_id, s.category, s.score FROM rating_scores s JOIN ratings r ON r.id = s.rating_id WHERE r.user_id = ?",
            (int(user_id),),
        ):
            scores.setdefault(int(s["rating_id"]), {})[s["category"]] = int(s["score"])
        return [{**{k: r[k] for k in r.keys()}, "scores": scores.get(int(r["rating_id"]), {})} for r in rows]

    def review_totals(self) -> dict[int, tuple[int, int]]:
        """film_id -> (number of reviewers'-round ratings, sum of all their scores).

        Judges'-round ratings are left out, so the reviewers' average is stable once the judges
        start. A person's score for a film is the sum of their three category scores, so
        total / count is the film's average score (3-30), kept as two integers for exact comparison.
        """
        rows = self.db.fetchall(
            """
            SELECT r.film_id AS film_id, COUNT(DISTINCT r.id) AS n, SUM(s.score) AS total
            FROM ratings r
            JOIN assignments a ON a.user_id = r.user_id AND a.film_id = r.film_id AND a.round = 'reviewers'
            JOIN rating_scores s ON s.rating_id = r.id
            GROUP BY r.film_id
            """
        )
        return {int(r["film_id"]): (int(r["n"]), int(r["total"])) for r in rows}

    def judge_totals(self) -> dict[int, tuple[int, int]]:
        """film_id -> (number of judges' ratings, sum of all their scores) for judges' pool films.

        A judge's rating counts whichever round it was made in (a judge who reviewed a pool film
        keeps that rating as their judge rating). Only people who hold the judge role count.
        """
        rows = self.db.fetchall(
            """
            SELECT r.film_id AS film_id, COUNT(DISTINCT r.id) AS n, SUM(s.score) AS total
            FROM ratings r
            JOIN films f ON f.id = r.film_id AND f.in_judges_pool = 1
            JOIN users u ON u.id = r.user_id AND u.is_judge = 1
            JOIN rating_scores s ON s.rating_id = r.id
            GROUP BY r.film_id
            """
        )
        return {int(r["film_id"]): (int(r["n"]), int(r["total"])) for r in rows}

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
