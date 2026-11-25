import random
from typing import Optional

from ..repositories.assignment_repo import AssignmentRepository
from ..repositories.film_repo import FilmRepository
from ..repositories.user_repo import UserRepository

# Every film is reviewed by this many different reviewers, and counts as "fully reviewed"
# once this many have submitted.
REVIEWS_PER_FILM = 2


class DistributionError(Exception):
    """A precondition isn't met; `code` is sent to the client."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class DistributionService:
    """Hands the films out to reviewers, and reports how far reviewing has got."""

    def __init__(self, users: UserRepository, films: FilmRepository, assignments: AssignmentRepository,
                 rng: Optional[random.Random] = None):
        self.users = users
        self.films = films
        self.assignments = assignments
        self.rng = rng or random.Random()

    # -- distribute / reset --------------------------------------------------

    def distribute(self) -> dict:
        """Give every film to REVIEWS_PER_FILM different reviewers, chosen at random.

        Runs once: refuses while any assignment exists (reset first). Each film goes to the
        reviewers who currently have the fewest films (ties broken at random), so everyone
        ends up with a share within one film of everyone else's.
        """
        if self.assignments.count() > 0:
            raise DistributionError("already_distributed",
                                    "Films have already been handed out. Reset the distribution first to run it again.")
        films = self.films.list_all()
        if not films:
            raise DistributionError("no_films", "There are no films to hand out. Import the spreadsheet first.")
        reviewers = [int(r["id"]) for r in self.users.list_with_role("reviewer")]
        if len(reviewers) < REVIEWS_PER_FILM:
            raise DistributionError(
                "too_few_reviewers",
                f"Every film needs {REVIEWS_PER_FILM} different reviewers, but only {len(reviewers)} "
                f"{'has' if len(reviewers) == 1 else 'have'} the reviewer role.")

        load = {uid: 0 for uid in reviewers}
        pairs: list[tuple[int, int]] = []
        order = list(films)
        self.rng.shuffle(order)
        for film in order:
            # Fewest films first; a random number breaks ties so nobody is favoured by id order.
            ranked = sorted(reviewers, key=lambda uid: (load[uid], self.rng.random()))
            for uid in ranked[:REVIEWS_PER_FILM]:
                pairs.append((uid, int(film["id"])))
                load[uid] += 1
        self.assignments.add_many(pairs)
        return {
            "films": len(films),
            "reviewers": len(reviewers),
            "assignments": len(pairs),
            "per_reviewer": {"min": min(load.values()), "max": max(load.values())},
        }

    def reset(self) -> dict:
        return self.assignments.reset_all()

    # -- hand assignment -----------------------------------------------------

    def assign(self, user_id: int, identifier: str) -> bool:
        """Hand one film to one person (reviewer or judge). False if they already had it.
        ValueError: they hold neither role. LookupError: unknown user or film."""
        user = self.users.get_by_id(user_id)
        film = self.films.get_by_identifier(identifier)
        if not user:
            raise LookupError("User not found")
        if not film:
            raise LookupError("Film not found")
        if not set(UserRepository.roles_of(user)) & {"reviewer", "judge"}:
            raise ValueError("Only reviewers and judges can be given films")
        return self.assignments.add(user_id, int(film["id"]))

    def unassign(self, user_id: int, identifier: str) -> str:
        film = self.films.get_by_identifier(identifier)
        if not film:
            raise LookupError("Film not found")
        return self.assignments.remove_unrated(user_id, int(film["id"]))

    # -- progress ------------------------------------------------------------

    def progress(self) -> dict:
        """How far reviewing has got: overall counter, one row per person, one row per film."""
        films = self.films.list_all()
        rows = self.assignments.list_with_people()

        by_film: dict[str, list[dict]] = {}
        per_user: dict[int, dict] = {}
        totals = {"assigned": 0, "seen": 0, "rated": 0}
        for r in rows:
            status = r["status"]
            by_film.setdefault(r["ia_identifier"], []).append(
                {"user_id": int(r["user_id"]), "email": r["email"], "status": status})
            counts = per_user.setdefault(int(r["user_id"]), {"assigned": 0, "seen": 0, "rated": 0})
            counts[status] += 1
            totals[status] += 1

        film_rows = []
        for f in films:
            assignees = by_film.get(f["ia_identifier"], [])
            rated = sum(1 for a in assignees if a["status"] == "rated")
            film_rows.append({
                "identifier": f["ia_identifier"],
                "title": f["title"] or f["ia_identifier"],
                "creator": f["creator"],
                "in_judges_pool": bool(f["in_judges_pool"]),
                "assignees": assignees,
                "rated": rated,
                "fully_reviewed": rated >= REVIEWS_PER_FILM,
            })
        fully = sum(1 for f in film_rows if f["fully_reviewed"])

        people = []
        for u in self.users.list_all():
            roles = UserRepository.roles_of(u)
            counts = per_user.get(int(u["id"]))
            if not (set(roles) & {"reviewer", "judge"}) and not counts:
                continue
            c = counts or {"assigned": 0, "seen": 0, "rated": 0}
            people.append({"id": int(u["id"]), "email": u["email"], "roles": roles, **c, "total": sum(c.values())})

        return {
            "overall": {
                "films": len(film_rows),
                "fully_reviewed": fully,
                "needing_reviews": len(film_rows) - fully,
                "reviews_per_film": REVIEWS_PER_FILM,
                "distributed": len(rows) > 0,
                "assignments": totals,
            },
            "people": people,
            "films": film_rows,
        }
