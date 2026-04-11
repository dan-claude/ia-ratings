import sqlite3
from typing import Any, Iterable, Optional

class Database:
    def __init__(self, path: str):
        self.path = path
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        # NOTE: each call returns a fresh connection.
        # SQLite itself is ACID-capable, but application-level atomicity requires
        # grouping related writes in a single transaction on a single connection.
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        # Enforce referential integrity.
        conn.execute("PRAGMA foreign_keys = ON;")

        # Concurrency + durability tuning suitable for a small web app.
        # - WAL improves read/write concurrency.
        # - synchronous=NORMAL is a common durability/performance trade-off.
        #   If you need maximum durability, use FULL.
        # - busy_timeout avoids immediate 'database is locked' errors under load.
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        return conn

    def _init_schema(self) -> None:
        conn = self.connect()
        try:
            # Base schema (idempotent).
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
              version INTEGER PRIMARY KEY,
              applied_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS users (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              email TEXT NOT NULL UNIQUE,
              password_hash TEXT NOT NULL,
              is_admin INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS films (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ia_identifier TEXT NOT NULL UNIQUE,
              title TEXT,
              description TEXT,
              collection TEXT NOT NULL,
              mediatype TEXT,
              metadata_json TEXT,
              updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS criteria (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              key TEXT NOT NULL UNIQUE,
              label TEXT NOT NULL,
              min_score INTEGER NOT NULL DEFAULT 1,
              max_score INTEGER NOT NULL DEFAULT 5,
              sort_order INTEGER NOT NULL,
              active INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS ratings (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id INTEGER NOT NULL,
              film_id INTEGER NOT NULL,
              created_at TEXT NOT NULL DEFAULT (datetime('now')),
              updated_at TEXT NOT NULL DEFAULT (datetime('now')),
              UNIQUE(user_id, film_id),
              FOREIGN KEY(user_id) REFERENCES users(id),
              FOREIGN KEY(film_id) REFERENCES films(id)
            );

            CREATE TABLE IF NOT EXISTS rating_scores (
              rating_id INTEGER NOT NULL,
              criteria_id INTEGER NOT NULL,
              score INTEGER NOT NULL,
              PRIMARY KEY (rating_id, criteria_id),
              FOREIGN KEY(rating_id) REFERENCES ratings(id),
              FOREIGN KEY(criteria_id) REFERENCES criteria(id)
            );

            CREATE INDEX IF NOT EXISTS idx_ratings_user ON ratings(user_id);
            CREATE INDEX IF NOT EXISTS idx_films_collection ON films(collection);
            """)

            # ---- MIGRATIONS ----
            # v1: Add users.is_admin for older databases.
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
            if "is_admin" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0;")
                conn.execute("INSERT OR IGNORE INTO schema_migrations (version) VALUES (1);")

            

            # v2: Add ratings.updated_at for older databases.
            rcols = {r["name"] for r in conn.execute("PRAGMA table_info(ratings)").fetchall()}
            if "updated_at" not in rcols:
                conn.execute("ALTER TABLE ratings ADD COLUMN updated_at TEXT NOT NULL DEFAULT (datetime('now'));")
                conn.execute("INSERT OR IGNORE INTO schema_migrations (version) VALUES (2);")
            
            # v3: Add films.description for older databases.
            fcols = {r["name"] for r in conn.execute("PRAGMA table_info(films)").fetchall()}
            if "description" not in fcols:
                conn.execute("ALTER TABLE films ADD COLUMN description TEXT;")
                conn.execute("INSERT OR IGNORE INTO schema_migrations (version) VALUES (3);")

            # v4: Add users.ia_username for Internet Archive SSO.
            ucols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
            if "ia_username" not in ucols:
                conn.execute("ALTER TABLE users ADD COLUMN ia_username TEXT;")
                conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_ia_username ON users(ia_username) WHERE ia_username IS NOT NULL;")
                conn.execute("INSERT OR IGNORE INTO schema_migrations (version) VALUES (4);")

# ---- SEED DATA ----
            conn.execute("""
              INSERT OR IGNORE INTO criteria (key, label, sort_order) VALUES
                ('originality', 'Originality', 1),
                ('use_of_archive_materials', 'Use of Archive Materials', 2)
            """)
            conn.commit()
        finally:
            conn.close()


    def fetchone(self, sql: str, params: Iterable[Any] = ()) -> Optional[sqlite3.Row]:
        conn = self.connect()
        try:
            return conn.execute(sql, tuple(params)).fetchone()
        finally:
            conn.close()

    def fetchall(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        conn = self.connect()
        try:
            return conn.execute(sql, tuple(params)).fetchall()
        finally:
            conn.close()
