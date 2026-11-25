import sqlite3
from typing import Any, Iterable, Optional

# Version of the schema below. The migration history restarted at 1 with the
# "major changes" rewrite (the old v1-v9 were deleted). To change the schema
# later, bump this and add a step that upgrades a database at the previous version.
SCHEMA_VERSION = 1

# Tables the old (pre-rewrite) app created and the new schema does not have.
# Finding one means the file is from the old app.
_LEGACY_TABLES = {"criteria", "film_notes", "app_settings"}


class LegacyDatabaseError(RuntimeError):
    """The database file was made by an older, incompatible version of the app."""


_SCHEMA = """
CREATE TABLE schema_migrations (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- People. `email` is the identity an admin invites (stored lower-case). Roles are
-- independent flags; a user with none sees no films. `password_hash` is unused for
-- now (reserved in case password registration is added later).
CREATE TABLE users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT,
  is_admin INTEGER NOT NULL DEFAULT 0 CHECK (is_admin IN (0, 1)),
  is_reviewer INTEGER NOT NULL DEFAULT 0 CHECK (is_reviewer IN (0, 1)),
  is_judge INTEGER NOT NULL DEFAULT 0 CHECK (is_judge IN (0, 1)),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Magic links. Only the SHA-256 of the link's secret is stored. A link can be used
-- repeatedly until `expires_at` (set by the admin) or until it is revoked; at most
-- one link per user is active (not revoked) at a time.
CREATE TABLE login_links (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  expires_at TEXT NOT NULL,
  revoked_at TEXT,
  FOREIGN KEY(user_id) REFERENCES users(id)
);
CREATE UNIQUE INDEX idx_login_links_active ON login_links(user_id) WHERE revoked_at IS NULL;

-- Server-side login sessions (only the SHA-256 of the random session id is stored).
CREATE TABLE user_sessions (
  sid_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(user_id) REFERENCES users(id)
);
CREATE INDEX idx_user_sessions_user ON user_sessions(user_id);

-- Films come only from the spreadsheet import. `in_judges_pool` marks the films
-- the judges rate (set when the admin confirms the pool).
CREATE TABLE films (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ia_identifier TEXT NOT NULL UNIQUE,
  title TEXT,
  creator TEXT,
  description TEXT,
  public_domain_works TEXT,
  ai_disclosure TEXT,
  in_judges_pool INTEGER NOT NULL DEFAULT 0 CHECK (in_judges_pool IN (0, 1)),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Which films a person has to rate, and how far they are: assigned (handed out),
-- seen (opened in the viewer), rated (scores submitted).
CREATE TABLE assignments (
  user_id INTEGER NOT NULL,
  film_id INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'assigned' CHECK (status IN ('assigned', 'seen', 'rated')),
  assigned_at TEXT NOT NULL DEFAULT (datetime('now')),
  seen_at TEXT,
  rated_at TEXT,
  PRIMARY KEY (user_id, film_id),
  FOREIGN KEY(user_id) REFERENCES users(id),
  FOREIGN KEY(film_id) REFERENCES films(id)
);
CREATE INDEX idx_assignments_film ON assignments(film_id);

-- One row per person per film, created when they submit (so it is final).
CREATE TABLE ratings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  film_id INTEGER NOT NULL,
  comment TEXT NOT NULL DEFAULT '' CHECK (length(comment) <= 1000),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (user_id, film_id),
  FOREIGN KEY(user_id) REFERENCES users(id),
  FOREIGN KEY(film_id) REFERENCES films(id)
);
CREATE INDEX idx_ratings_film ON ratings(film_id);

-- One score per category per rating. Category keys are fixed in the code (server/categories.py).
CREATE TABLE rating_scores (
  rating_id INTEGER NOT NULL,
  category TEXT NOT NULL,
  score INTEGER NOT NULL CHECK (score BETWEEN 1 AND 10),
  PRIMARY KEY (rating_id, category),
  FOREIGN KEY(rating_id) REFERENCES ratings(id)
);
"""


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
            tables = {
                r["name"]
                for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            }
            if not tables:
                with conn:  # one transaction: a half-built schema is never left behind
                    conn.execute("BEGIN")
                    for stmt in _split_statements(_SCHEMA):
                        conn.execute(stmt)
                    conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (SCHEMA_VERSION,))
                return
            self._check_not_legacy(conn, tables)
        finally:
            conn.close()

    def _check_not_legacy(self, conn: sqlite3.Connection, tables: set[str]) -> None:
        """Refuse to run on a database from the old app (or from a newer one)."""
        problem = None
        if "schema_migrations" not in tables:
            problem = "it has no schema_migrations table"
        elif tables & _LEGACY_TABLES:
            problem = f"it still has the old table(s) {sorted(tables & _LEGACY_TABLES)}"
        else:
            row = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
            version = row["v"] if row else None
            if version != SCHEMA_VERSION:
                problem = f"its schema version is {version}, this app needs {SCHEMA_VERSION}"
            elif "is_reviewer" not in {r["name"] for r in conn.execute("PRAGMA table_info(users)")}:
                problem = "its users table has the old layout"
        if problem:
            raise LegacyDatabaseError(
                f"The database file {self.path!r} was made by an older version of this app and cannot be used: "
                f"{problem}. Back it up if you need the data, then delete the file (and its -wal and -shm "
                "files) so the app can create a fresh database."
            )

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


def _split_statements(script: str) -> list[str]:
    """Split the schema script into single statements (there are no ';' inside any of them)."""
    lines = [ln for ln in script.splitlines() if not ln.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]
