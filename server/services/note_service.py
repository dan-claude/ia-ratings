import csv
from io import StringIO

from ..repositories.film_repo import FilmRepository
from .csv_utils import csv_safe
from ..repositories.note_repo import NoteRepository, author_name

MAX_NOTE_LENGTH = 5000


def _note_json(row) -> dict:
    # SQLite stores UTC as "YYYY-MM-DD HH:MM:SS"; hand clients an unambiguous ISO-8601 string.
    return {
        "id": int(row["id"]),
        "author": author_name(row),
        "createdAt": str(row["created_at"]).replace(" ", "T") + "Z",
        "text": row["body"],
    }


class NoteService:
    def __init__(self, films: FilmRepository, notes: NoteRepository):
        self.films = films
        self.notes = notes

    def _film_id(self, identifier: str) -> int:
        film = self.films.get_by_identifier(identifier)
        if not film:
            raise LookupError("Film not found")
        return int(film["id"])

    def list_notes(self, identifier: str) -> list[dict]:
        return [_note_json(r) for r in self.notes.list_for_film(self._film_id(identifier))]

    def add_note(self, user_id: int, identifier: str, text) -> dict:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Note text is required")
        text = text.strip()
        if len(text) > MAX_NOTE_LENGTH:
            raise ValueError(f"Note is too long (max {MAX_NOTE_LENGTH} characters)")
        film_id = self._film_id(identifier)
        return _note_json(self.notes.add(film_id, user_id, text))

    def export_csv(self) -> str:
        """All notes on films in the active collection, as CSV (admin download)."""
        out = StringIO()
        writer = csv.writer(out)
        writer.writerow(["created_at", "author", "identifier", "title", "text"])
        for r in self.notes.list_for_export(self.films.collection):
            writer.writerow([r["created_at"], csv_safe(author_name(r)), csv_safe(r["identifier"]), csv_safe(r["title"] or ""), csv_safe(r["body"])])
        return out.getvalue()
