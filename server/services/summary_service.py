import csv
from io import StringIO
from ..repositories.criteria_repo import CriteriaRepository
from ..repositories.film_repo import FilmRepository
from ..repositories.rating_repo import RatingRepository

class SummaryService:
    def __init__(self, criteria: CriteriaRepository, films: FilmRepository, ratings: RatingRepository, collection):
        """collection: a slug, or a zero-arg callable returning the current slug."""
        self.criteria = criteria
        self.films = films
        self.ratings = ratings
        self._collection = collection

    @property
    def collection(self) -> str:
        c = self._collection
        return c() if callable(c) else c

    def admin_list_criteria(self) -> list[dict]:
        return [dict(r) for r in self.criteria.list_all()]

    def admin_add_criterion(self, key: str, label: str, min_score: int, max_score: int, sort_order: int, active: int) -> None:
        import sqlite3, re
        if not key or not label:
            raise ValueError("key and label required")
        if not re.match(r"^[a-z0-9_]+$", key):
            raise ValueError("key must be lowercase letters/numbers/underscore")
        if min_score >= max_score:
            raise ValueError("invalid min/max")
        try:
            self.criteria.insert(key, label, min_score, max_score, sort_order, active)
        except sqlite3.IntegrityError as e:
            raise KeyError("criterion key already exists") from e

    def admin_patch_criterion(self, cid: int, label, min_score, max_score, sort_order, active) -> None:
        row = self.criteria.get_by_id(cid)
        if not row:
            raise LookupError("not found")

        new_label = label if label is not None else row["label"]
        new_min = int(min_score) if min_score is not None else int(row["min_score"])
        new_max = int(max_score) if max_score is not None else int(row["max_score"])
        new_so = int(sort_order) if sort_order is not None else int(row["sort_order"])
        new_active = int(active) if active is not None else int(row["active"])

        if new_min >= new_max:
            raise ValueError("invalid min/max")

        self.criteria.update(cid, new_label, new_min, new_max, new_so, new_active)

    def admin_summary(self) -> dict:
        crit = self.criteria.list_active()
        films = self.films.list_all_in_collection()

        out_films = []
        for f in films:
            film_id = int(f["id"])
            rated_n = self.ratings.count_ratings_for_film(film_id)
            averages = {}
            for c in crit:
                avg = self.ratings.avg_score_for_film_criterion(film_id, int(c["id"]))
                averages[c["key"]] = avg
            out_films.append({
                "identifier": f["identifier"],
                "title": f["title"],
                "ratingsCount": rated_n,
                "averages": averages,
            })

        return {
            "criteria": [{"key": c["key"], "label": c["label"], "sortOrder": c["sort_order"]} for c in crit],
            "films": out_films,
        }

    def admin_ratings_csv(self) -> str:
        crit = self.ratings.list_active_criteria_for_export()
        ratings = self.ratings.list_ratings_for_export(self.collection)

        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(["created_at", "user_email", "identifier", "title", *[c["key"] for c in crit]])

        for r in ratings:
            scores = []
            for c in crit:
                s = self.ratings.get_score(int(r["rating_id"]), int(c["id"]))
                scores.append("" if s is None else s)
            writer.writerow([r["created_at"], r["user_email"], r["identifier"], r["title"], *scores])

        return output.getvalue()
