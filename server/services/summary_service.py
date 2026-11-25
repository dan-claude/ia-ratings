import csv
from io import StringIO

from ..categories import CATEGORIES
from ..repositories.rating_repo import RatingRepository
from .csv_utils import csv_safe


class SummaryService:
    def __init__(self, ratings: RatingRepository):
        self.ratings = ratings

    def admin_ratings_csv(self) -> str:
        """Every submitted rating, one row each, including the person's comment."""
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "created_at", "user_email", "identifier", "title",
            *[c["key"] for c in CATEGORIES], "total", "comment",
        ])
        for r in self.ratings.list_for_export():
            scores = [r["scores"].get(c["key"]) for c in CATEGORIES]
            writer.writerow([
                r["created_at"], csv_safe(r["user_email"]), csv_safe(r["identifier"]), csv_safe(r["title"]),
                *["" if s is None else s for s in scores],
                sum(s for s in scores if s is not None),
                csv_safe(r["comment"]),
            ])
        return output.getvalue()
