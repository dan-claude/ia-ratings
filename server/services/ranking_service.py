import csv
from fractions import Fraction
from io import StringIO
from typing import Optional

from ..repositories.assignment_repo import AssignmentRepository
from ..repositories.film_repo import FilmRepository
from ..repositories.rating_repo import RatingRepository
from ..repositories.user_repo import UserRepository
from .csv_utils import csv_safe
from .distribution_service import REVIEWS_PER_FILM, DistributionService

DEFAULT_POOL_SIZE = 20


class PoolError(Exception):
    """The judges' pool can't be changed right now; `code` and `extra` go to the client."""

    def __init__(self, code: str, message: str, extra: Optional[dict] = None):
        super().__init__(message)
        self.code = code
        self.extra = extra or {}


def _ranked(rows: list[dict]) -> list[dict]:
    """Sort highest average first and give each film a rank (equal averages share a rank: 1, 2, 2, 4).
    Averages are compared exactly (as fractions), never as rounded decimals. Ties are listed
    alphabetically by title so the order is stable. Films nobody has rated come last, unranked."""
    rated = [r for r in rows if r["reviews"] > 0]
    unrated = [r for r in rows if r["reviews"] == 0]
    rated.sort(key=lambda r: (-Fraction(r["total"], r["reviews"]), r["title"].lower(), r["identifier"]))
    unrated.sort(key=lambda r: (r["title"].lower(), r["identifier"]))
    prev, rank = None, 0
    for i, r in enumerate(rated, 1):
        avg = Fraction(r["total"], r["reviews"])
        if avg != prev:
            rank, prev = i, avg
        r["rank"] = rank
    for r in unrated:
        r["rank"] = None
    return rated + unrated


class RankingService:
    """Films ranked by their reviewers' average score, and the judges' pool chosen from the top."""

    def __init__(self, users: UserRepository, films: FilmRepository, assignments: AssignmentRepository,
                 ratings: RatingRepository, distribution: DistributionService):
        self.users = users
        self.films = films
        self.assignments = assignments
        self.ratings = ratings
        self.distribution = distribution

    # -- rankings ------------------------------------------------------------

    def rankings(self) -> list[dict]:
        """Every film with its reviewers' average (highest first) and all its details."""
        totals = self.ratings.review_totals()
        rows = []
        for f in self.films.list_all():
            n, total = totals.get(int(f["id"]), (0, 0))
            rows.append({
                "id": int(f["id"]),
                "identifier": f["ia_identifier"],
                "title": f["title"] or f["ia_identifier"],
                "creator": f["creator"],
                "description": f["description"],
                "public_domain_works": f["public_domain_works"],
                "ai_disclosure": f["ai_disclosure"],
                "in_judges_pool": bool(f["in_judges_pool"]),
                "reviews": n,
                "total": total,
                # For display only; compare with total / reviews (exact), never with this.
                "average": round(total / n, 2) if n else None,
            })
        return _ranked(rows)

    def rankings_csv(self) -> str:
        out = StringIO()
        w = csv.writer(out)
        w.writerow(["rank", "title", "creator", "average", "reviews", "total", "identifier",
                    "description", "public_domain_works", "ai_disclosure", "in_judges_pool"])
        for r in self.rankings():
            w.writerow([
                "" if r["rank"] is None else r["rank"], csv_safe(r["title"]), csv_safe(r["creator"] or ""),
                "" if r["average"] is None else r["average"], r["reviews"], r["total"], csv_safe(r["identifier"]),
                csv_safe(r["description"] or ""), csv_safe(r["public_domain_works"] or ""),
                csv_safe(r["ai_disclosure"] or ""), "yes" if r["in_judges_pool"] else "no",
            ])
        return out.getvalue()

    # -- judges' pool ----------------------------------------------------------

    def _blocked_by_missing_reviews(self, ranked: list[dict]) -> Optional[PoolError]:
        """D17: nothing can be previewed or confirmed until every film has both its reviews."""
        progress = self.distribution.progress()
        if not ranked:
            return PoolError("no_films", "There are no films yet.")
        missing = [{"identifier": f["identifier"], "title": f["title"], "rated": f["rated"], "needed": REVIEWS_PER_FILM}
                   for f in progress["films"] if not f["fully_reviewed"]]
        if not missing:
            return None
        o = progress["overall"]
        return PoolError(
            "reviews_missing",
            f"{o['fully_reviewed']} of {o['films']} films fully reviewed; {o['needing_reviews']} still "
            f"{'needs' if o['needing_reviews'] == 1 else 'need'} at least one review. "
            "The judges' pool can be previewed once every film has both its reviews.",
            {"overall": o, "missing": missing},
        )

    @staticmethod
    def _valid_cut(ranked: list[dict], n: int) -> bool:
        """The film at rank n must score strictly higher than the film after it."""
        if n >= len(ranked):
            return True
        a, b = ranked[n - 1], ranked[n]
        return Fraction(a["total"], a["reviews"]) > Fraction(b["total"], b["reviews"])

    def preview(self, count) -> dict:
        """The films a pool of `count` would hold. Nothing is changed. PoolError if blocked."""
        ranked = self.rankings()
        blocked = self._blocked_by_missing_reviews(ranked)
        if blocked:
            raise blocked
        n = self._parse_count(count, len(ranked))
        valid = self._valid_cut(ranked, n)
        valid_counts = [k for k in range(1, len(ranked) + 1) if self._valid_cut(ranked, k)]
        lower = max((k for k in valid_counts if k < n), default=None)
        higher = min((k for k in valid_counts if k > n), default=None)
        return {
            "count": n,
            "valid": valid,
            "films": ranked[:n],
            "tie": None if valid else {
                "message": f"Film {n} and film {n + 1} have exactly the same average score, so the cut-off would be unfair.",
                "nearest_valid_counts": {"lower": lower, "higher": higher},
            },
            "pool_exists": any(r["in_judges_pool"] for r in ranked),
            "total_films": len(ranked),
        }

    @staticmethod
    def _parse_count(count, total: int) -> int:
        if count is None:
            return min(DEFAULT_POOL_SIZE, total)
        if isinstance(count, bool) or not isinstance(count, int):
            raise ValueError("count must be a whole number")
        if not 1 <= count <= total:
            raise ValueError(f"count must be between 1 and {total}")
        return count

    def confirm(self, count) -> dict:
        """Make the top `count` films the judges' pool and give all of them to every judge."""
        pv = self.preview(count)          # same checks as the preview: blocked, bad count
        if pv["pool_exists"]:
            raise PoolError("pool_already_set", "The judges' pool is already set. Clear it first to choose again.")
        if not pv["valid"]:
            raise PoolError("tie_at_cutoff", pv["tie"]["message"], {"tie": pv["tie"]})
        self.films.set_judges_pool([f["id"] for f in pv["films"]])
        assigned = self.assign_pool()
        return {"count": pv["count"], "judges": assigned["judges"], "assigned": assigned["assigned"]}

    def assign_pool(self) -> dict:
        """Give every pool film to every judge (idempotent). A judge who already has a film from
        the reviewing round keeps that assignment and rating as they are; they don't rate it again."""
        pool = [f for f in self.films.list_all() if f["in_judges_pool"]]
        if not pool:
            raise PoolError("no_pool", "There is no judges' pool yet.")
        judges = [int(u["id"]) for u in self.users.list_with_role("judge")]
        pairs = [(j, int(f["id"])) for j in judges for f in pool]
        return {"judges": len(judges), "films": len(pool), "assigned": self.assignments.add_many(pairs, "judges")}

    def clear_pool(self) -> dict:
        removed = self.assignments.clear_judges_round()
        if removed is None:
            raise PoolError("judges_have_rated", "Judges have already rated pool films, so the pool can't be cleared. "
                                                 "Use the full distribution reset to start over.")
        self.films.set_judges_pool([])
        return {"removed_assignments": removed}

    def pool_status(self) -> dict:
        ranked = self.rankings()
        pool = [r for r in ranked if r["in_judges_pool"]]
        progress = self.distribution.progress()
        per_judge: dict[int, dict] = {}
        pool_ids = {r["identifier"] for r in pool}
        for f in progress["films"]:
            if f["identifier"] in pool_ids:
                for a in f["assignees"]:
                    per_judge.setdefault(a["user_id"], {})[f["identifier"]] = a["status"]
        judges = []
        for u in self.users.list_with_role("judge"):
            statuses = per_judge.get(int(u["id"]), {})
            counts = {s: sum(1 for v in statuses.values() if v == s) for s in ("assigned", "seen", "rated")}
            judges.append({"id": int(u["id"]), "email": u["email"], "films": len(statuses), **counts})
        return {"exists": bool(pool), "films": pool, "judges": judges}
