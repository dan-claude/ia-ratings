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
              ia_identifier TEXT NOT NULL,
              title TEXT,
              description TEXT,
              collection TEXT NOT NULL,
              mediatype TEXT,
              metadata_json TEXT,
              updated_at TEXT NOT NULL DEFAULT (datetime('now')),
              UNIQUE (ia_identifier, collection)
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

            # v5: Add users.github_id / users.github_username for GitHub OAuth login.
            # github_id (GitHub's numeric account id) is the stable key; the
            # username can change on GitHub, so it is stored only for display.
            ucols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
            if "github_id" not in ucols:
                conn.execute("ALTER TABLE users ADD COLUMN github_id TEXT;")
                conn.execute("ALTER TABLE users ADD COLUMN github_username TEXT;")
                conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_github_id ON users(github_id) WHERE github_id IS NOT NULL;")
                conn.execute("INSERT OR IGNORE INTO schema_migrations (version) VALUES (5);")

            # v6: app_settings key/value table (e.g. the active film collection,
            # which admins change from the admin panel).
            tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            if "app_settings" not in tables:
                conn.execute("""
                  CREATE TABLE app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                  )
                """)
                conn.execute("INSERT OR IGNORE INTO schema_migrations (version) VALUES (6);")

            # v7: a film is unique per (ia_identifier, collection), not per identifier alone,
            # so the same archive.org item can be in several collections (e.g. two contest
            # years) with separate ratings. Older databases need the films table rebuilt
            # (SQLite can't drop a column's UNIQUE constraint in place).
            if self._films_unique_on_identifier_only(conn):
                self._rebuild_films_table(conn)
            conn.execute("INSERT OR IGNORE INTO schema_migrations (version) VALUES (7);")

            # v8: user roles beyond admin (currently admin + judge) and judges' film notes.
            # Roles are columns on users (is_admin already existed; is_judge is new) so a
            # backup/restore of the users table carries them automatically.
            ucols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
            if "is_judge" not in ucols:
                conn.execute("ALTER TABLE users ADD COLUMN is_judge INTEGER NOT NULL DEFAULT 0;")
            tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            if "film_notes" not in tables:
                conn.execute("""
                  CREATE TABLE film_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    film_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    body TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY(film_id) REFERENCES films(id),
                    FOREIGN KEY(user_id) REFERENCES users(id)
                  )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_film_notes_film ON film_notes(film_id)")
            conn.execute("INSERT OR IGNORE INTO schema_migrations (version) VALUES (8);")

            # v9: server-side login sessions. The signed cookie carries a random session id;
            # only its SHA-256 is stored here, so logout (and a backup restore) can revoke
            # sessions instead of leaving them valid until the cookie expires.
            tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            if "user_sessions" not in tables:
                conn.execute("""
                  CREATE TABLE user_sessions (
                    sid_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY(user_id) REFERENCES users(id)
                  )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_user_sessions_user ON user_sessions(user_id)")
            conn.execute("INSERT OR IGNORE INTO schema_migrations (version) VALUES (9);")

# ---- SEED DATA ----
            conn.execute("""
              INSERT OR IGNORE INTO criteria (key, label, sort_order) VALUES
                ('originality', 'Originality', 1),
                ('use_of_archive_materials', 'Use of Archive Materials', 2)
            """)
            conn.commit()
        finally:
            conn.close()


    @staticmethod
    def _films_unique_on_identifier_only(conn: sqlite3.Connection) -> bool:
        """True if films still has the old UNIQUE(ia_identifier) constraint."""
        for idx in conn.execute("PRAGMA index_list(films)").fetchall():
            if idx["unique"]:
                cols = [c["name"] for c in conn.execute(f'PRAGMA index_info("{idx["name"]}")').fetchall()]
                if cols == ["ia_identifier"]:
                    return True
        return False

    @staticmethod
    def _rebuild_films_table(conn: sqlite3.Connection) -> None:
        """Rebuild films with UNIQUE(ia_identifier, collection), keeping every id.

        Follows SQLite's documented procedure (create new, copy, drop old, rename):
        foreign keys are switched off for the copy because ratings.film_id points at
        films(id); ids are preserved, so every rating keeps pointing at the same film.
        All-or-nothing: any failure rolls back and leaves the old table untouched.
        """
        conn.commit()  # PRAGMA foreign_keys is a no-op inside a transaction
        conn.execute("PRAGMA foreign_keys = OFF;")
        try:
            conn.execute("BEGIN")
            conn.execute("""
              CREATE TABLE films_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ia_identifier TEXT NOT NULL,
                title TEXT,
                description TEXT,
                collection TEXT NOT NULL,
                mediatype TEXT,
                metadata_json TEXT,
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE (ia_identifier, collection)
              )
            """)
            conn.execute("""
              INSERT INTO films_new (id, ia_identifier, title, description, collection, mediatype, metadata_json, updated_at)
              SELECT id, ia_identifier, title, description, collection, mediatype, metadata_json, updated_at FROM films
            """)
            conn.execute("DROP TABLE films")
            conn.execute("ALTER TABLE films_new RENAME TO films")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_films_collection ON films(collection)")
            if conn.execute("PRAGMA foreign_key_check").fetchall():
                raise sqlite3.IntegrityError("foreign key check failed after rebuilding films")
            conn.execute("INSERT OR IGNORE INTO schema_migrations (version) VALUES (7)")
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.execute("PRAGMA foreign_keys = ON;")

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
