from typing import Dict
from ..repositories.film_repo import FilmRepository
from ..repositories.criteria_repo import CriteriaRepository
from ..repositories.rating_repo import RatingRepository

class RatingService:
    def __init__(self, films: FilmRepository, criteria: CriteriaRepository, ratings: RatingRepository):
        self.films = films
        self.criteria = criteria
        self.ratings = ratings

    def list_active_criteria(self) -> list[dict]:
        return [dict(r) for r in self.criteria.list_active()]

    def get_next_unrated_film(self, user_id: int) -> dict | None:
        row = self.films.get_next_unrated_for_user(user_id)
        if not row:
            return None
        return {"identifier": row["ia_identifier"], "title": row["title"], "description": (row["description"] if ("description" in row.keys()) else None)}

    def count_films(self) -> int:
        return self.films.count()

    def get_film_by_identifier(self, identifier: str) -> dict | None:
        row = self.films.get_by_identifier(identifier)
        if not row:
            return None
        return {"identifier": row["ia_identifier"], "title": row["title"], "description": (row["description"] if ("description" in row.keys()) else None)}

    def submit_rating(self, user_id: int, identifier: str, scores: Dict[str, int]) -> None:
        if not isinstance(scores, dict):
            raise ValueError("scores object required")

        film_row = self.films.get_by_identifier(identifier)
        if not film_row:
            raise LookupError("Film not found (sync first)")

        crit = self.criteria.list_active()
        for c in crit:
            if c["key"] not in scores:
                raise ValueError(f"Missing score for: {c['key']}")

        validated: list[tuple[int, int]] = []
        for c in crit:
            try:
                n = int(scores[c["key"]])
            except Exception as e:
                raise ValueError(f"Score for {c['key']} must be integer") from e
            if n < c["min_score"] or n > c["max_score"]:
                raise ValueError(f"Score for {c['key']} must be {c['min_score']}-{c['max_score']}")
            validated.append((int(c["id"]), n))

        # IMPORTANT: submit the rating and its scores in a single transaction.
        # This prevents partially-written ratings if the process crashes between steps.
        self.ratings.upsert_rating_with_scores(user_id, int(film_row["id"]), validated)
