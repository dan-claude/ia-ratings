from typing import Optional

from ..categories import CATEGORIES, CATEGORY_KEYS, MAX_COMMENT_LENGTH, MAX_SCORE, MIN_SCORE
from ..repositories.assignment_repo import AssignmentRepository
from ..repositories.film_repo import FilmRepository
from ..repositories.rating_repo import AlreadyRated, RatingRepository
from ..repositories.user_repo import UserRepository


class NothingToRate(Exception):
    """There is no film to show; `code` says why (the API sends it to the client)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class RatingService:
    """What a reviewer or judge sees and does: open their next film, submit scores and a comment.

    Only people holding the reviewer or judge role take part (admin alone does not rate),
    and only on films assigned to them.
    """

    def __init__(self, users: UserRepository, films: FilmRepository, assignments: AssignmentRepository,
                 ratings: RatingRepository):
        self.users = users
        self.films = films
        self.assignments = assignments
        self.ratings = ratings

    @staticmethod
    def list_categories() -> list[dict]:
        return [{**c, "min": MIN_SCORE, "max": MAX_SCORE} for c in CATEGORIES]

    def _can_rate(self, user_id: int) -> bool:
        row = self.users.get_by_id(user_id)
        return bool(row) and bool(set(UserRepository.roles_of(row)) & {"reviewer", "judge"})

    def _film_payload(self, film, user_id: int, status: str) -> dict:
        payload = {
            "identifier": film["ia_identifier"],
            "title": film["title"] or film["ia_identifier"],
            "creator": film["creator"],
            "description": film["description"],
            "publicDomainWorks": film["public_domain_works"],
            "aiDisclosure": film["ai_disclosure"],
            "archiveUrl": f"https://archive.org/details/{film['ia_identifier']}",
            "embedUrl": f"https://archive.org/embed/{film['ia_identifier']}",
            "status": status,
        }
        if status == "rated":
            payload["rating"] = self.ratings.get_for_user_film(user_id, int(film["id"]))
        return payload

    def get_next_film(self, user_id: int) -> dict:
        """The film to rate next (opening it marks it `seen`). Raises NothingToRate when none."""
        if not self._can_rate(user_id):
            raise NothingToRate("no_role", "Your account doesn't have a reviewing role yet. Ask an admin to give you one.")
        if self.films.count() == 0:
            raise NothingToRate("no_films", "The film database hasn't been set up yet. An admin needs to import the films.")
        if self.assignments.count_for_user(user_id) == 0:
            raise NothingToRate("no_assignments", "No films have been assigned to you yet.")
        nxt = self.assignments.next_for_user(user_id)
        if not nxt:
            raise NothingToRate("all_rated", "You've rated every film assigned to you — thank you!")
        film = self.films.get_by_id(int(nxt["film_id"]))
        self.assignments.mark_seen(user_id, int(film["id"]))
        return self._film_payload(film, user_id, "seen")

    def get_film(self, user_id: int, identifier: str) -> Optional[dict]:
        """One of the person's own films (opening an unopened one marks it `seen`), else None."""
        if not self._can_rate(user_id):
            return None
        film = self.films.get_by_identifier(identifier)
        a = self.assignments.get(user_id, int(film["id"])) if film else None
        if not a:
            return None
        if a["status"] == "assigned":
            self.assignments.mark_seen(user_id, int(film["id"]))
        status = "seen" if a["status"] == "assigned" else a["status"]
        return self._film_payload(film, user_id, status)

    def submit_rating(self, user_id: int, identifier: str, scores, comment=None) -> int:
        """Record the person's final rating. Returns their total (the sum of the categories).

        ValueError: bad input (400). LookupError: not your film (404). AlreadyRated: (409).
        """
        if not isinstance(scores, dict):
            raise ValueError("scores object required")
        unknown = [k for k in scores if k not in CATEGORY_KEYS]
        if unknown:
            raise ValueError(f"Unknown category: {unknown[0]}")
        validated: dict[str, int] = {}
        for key in CATEGORY_KEYS:
            if key not in scores:
                raise ValueError(f"Missing score for: {key}")
            n = scores[key]
            if isinstance(n, bool) or not isinstance(n, int):
                raise ValueError(f"Score for {key} must be a whole number")
            if not MIN_SCORE <= n <= MAX_SCORE:
                raise ValueError(f"Score for {key} must be {MIN_SCORE}-{MAX_SCORE}")
            validated[key] = n

        if comment is None:
            comment = ""
        if not isinstance(comment, str):
            raise ValueError("comment must be text")
        comment = comment.strip()
        if len(comment) > MAX_COMMENT_LENGTH:
            raise ValueError(f"comment is too long (maximum {MAX_COMMENT_LENGTH} characters)")

        film = self.films.get_by_identifier(identifier) if self._can_rate(user_id) else None
        if not film:
            raise LookupError("Film not found")
        self.ratings.submit(user_id, int(film["id"]), validated, comment)
        return sum(validated.values())


__all__ = ["RatingService", "NothingToRate", "AlreadyRated"]
