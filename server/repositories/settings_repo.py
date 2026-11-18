import re
from typing import Optional

from ..db import Database

# Internet Archive collection identifiers: letters, digits, '.', '_' and '-'.
COLLECTION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


class AppSettingsRepository:
    """Key/value settings that admins change at runtime (table `app_settings`)."""

    def __init__(self, db: Database, default_collection: str):
        self.db = db
        self.default_collection = default_collection

    def get(self, key: str) -> Optional[str]:
        row = self.db.fetchone("SELECT value FROM app_settings WHERE key = ?", (key,))
        return row["value"] if row else None

    def set(self, key: str, value: str) -> None:
        conn = self.db.connect()
        try:
            conn.execute(
                "INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, datetime('now')) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')",
                (key, value),
            )
            conn.commit()
        finally:
            conn.close()

    # -- the active film collection ------------------------------------------

    def get_collection(self) -> str:
        """The collection raters see and sync/import use; the built-in default until set."""
        return self.get("collection") or self.default_collection

    @staticmethod
    def validate_collection(collection) -> str:
        """Return the trimmed collection name, or raise ValueError with a message for the admin."""
        collection = (collection or "").strip() if isinstance(collection, str) or collection is None else ""
        if not COLLECTION_RE.match(collection):
            raise ValueError(
                "Collection must be the name of an archive.org collection: letters, digits, '.', '_' or '-' (max 100 characters)"
            )
        return collection

    def set_collection(self, collection: str) -> str:
        collection = self.validate_collection(collection)
        self.set("collection", collection)
        return collection

    def collections_in_use(self) -> list[dict]:
        """Every collection that has films in the database, with film counts."""
        rows = self.db.fetchall(
            "SELECT collection AS name, COUNT(1) AS films FROM films GROUP BY collection ORDER BY collection"
        )
        return [{"name": r["name"], "films": int(r["films"])} for r in rows]
