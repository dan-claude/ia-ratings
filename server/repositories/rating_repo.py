import sqlite3
from ..db import Database

class RatingRepository:
    def __init__(self, db: Database):
        self.db = db

    def upsert_rating(self, user_id: int, film_id: int) -> int:
        """Create or update a rating row and return its id.

        Note: This method commits within its own transaction. For application-
        level atomicity when also writing scores, prefer upsert_rating_with_scores().
        """
        conn = self.db.connect()
        try:
            self._upsert_rating_row(conn, user_id, film_id)
            row = conn.execute(
                "SELECT id FROM ratings WHERE user_id=? AND film_id=?",
                (user_id, film_id),
            ).fetchone()
            conn.commit()
            return int(row["id"])
        finally:
            conn.close()

    def upsert_scores_bulk(self, rating_id: int, scores: list[tuple[int,int]]) -> None:
        """Upsert a set of criterion scores for a rating.

        Note: This method commits within its own transaction. For application-
        level atomicity when also creating/updating the rating row, prefer
        upsert_rating_with_scores().
        """
        conn = self.db.connect()
        try:
            self._upsert_scores_bulk(conn, rating_id, scores)
            conn.commit()
        finally:
            conn.close()

    def upsert_rating_with_scores(
        self,
        user_id: int,
        film_id: int,
        scores: list[tuple[int,int]],
    ) -> int:
        """Atomically upsert a rating and all of its scores in one transaction.

        This is the primary method the service layer should use. It guarantees
        that the rating row and its per-criterion scores are written together.

        Returns:
            rating_id: the id of the rating row.
        """
        conn = self.db.connect()
        try:
            # IMMEDIATE: acquire a write lock up front to reduce mid-transaction lock errors.
            conn.execute("BEGIN IMMEDIATE")
            self._upsert_rating_row(conn, user_id, film_id)
            row = conn.execute(
                "SELECT id FROM ratings WHERE user_id=? AND film_id=?",
                (user_id, film_id),
            ).fetchone()
            rating_id = int(row["id"])
            self._upsert_scores_bulk(conn, rating_id, scores)
            conn.commit()
            return rating_id
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _upsert_rating_row(self, conn: sqlite3.Connection, user_id: int, film_id: int) -> None:
        """Internal: upsert rating row using an existing connection."""
        conn.execute(
                """
                INSERT INTO ratings (user_id, film_id, updated_at)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(user_id, film_id) DO UPDATE SET updated_at=datetime('now')
                """,
                (user_id, film_id),
            )

    def _upsert_scores_bulk(self, conn: sqlite3.Connection, rating_id: int, scores: list[tuple[int,int]]) -> None:
        """Internal: upsert score rows using an existing connection."""
        for criteria_id, score in scores:
            conn.execute(
                    """
                    INSERT INTO rating_scores (rating_id, criteria_id, score)
                    VALUES (?, ?, ?)
                    ON CONFLICT(rating_id, criteria_id) DO UPDATE SET score=excluded.score
                    """,
                    (rating_id, criteria_id, score),
                )

    def list_active_criteria_for_export(self) -> list[sqlite3.Row]:
        conn = self.db.connect()
        try:
            return conn.execute(
                "SELECT id, key, sort_order FROM criteria WHERE active=1 ORDER BY sort_order"
            ).fetchall()
        finally:
            conn.close()

    def list_ratings_for_export(self, collection: str) -> list[sqlite3.Row]:
        conn = self.db.connect()
        try:
            return conn.execute(
                """
                SELECT r.id as rating_id, r.created_at, u.email as user_email,
                       f.ia_identifier as identifier, f.title as title
                FROM ratings r
                JOIN users u ON u.id = r.user_id
                JOIN films f ON f.id = r.film_id
                WHERE f.collection=?
                ORDER BY r.created_at DESC
                """,
                (collection,),
            ).fetchall()
        finally:
            conn.close()

    def get_score(self, rating_id: int, criteria_id: int) -> int | None:
        row = self.db.fetchone(
            "SELECT score FROM rating_scores WHERE rating_id=? AND criteria_id=?",
            (rating_id, criteria_id),
        )
        return None if not row else int(row["score"])

    def count_ratings_for_film(self, film_id: int) -> int:
        row = self.db.fetchone("SELECT COUNT(*) as n FROM ratings WHERE film_id=?", (film_id,))
        return int(row["n"]) if row else 0

    def avg_score_for_film_criterion(self, film_id: int, criteria_id: int) -> float | None:
        row = self.db.fetchone(
            """
            SELECT AVG(rs.score) as avgScore
            FROM ratings r
            JOIN rating_scores rs ON rs.rating_id = r.id
            WHERE r.film_id = ? AND rs.criteria_id = ?
            """,
            (film_id, criteria_id),
        )
        return None if (not row or row["avgScore"] is None) else float(row["avgScore"])
