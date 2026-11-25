import sqlite3
from typing import Optional

from ..db import Database

# Roles a user can hold; each maps to an INTEGER 0/1 column on users.
# The roles are independent: holding one never implies another.
ROLE_COLUMNS = {"admin": "is_admin", "reviewer": "is_reviewer", "judge": "is_judge"}

_COLUMNS = "id, email, is_admin, is_reviewer, is_judge, created_at"


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


class UserRepository:
    def __init__(self, db: Database):
        self.db = db

    def create_user(self, email: str, roles: list[str] | tuple[str, ...] = ()) -> int:
        """Create a user (email is stored lower-case) holding exactly `roles`.

        Raises ValueError for an unknown role and sqlite3.IntegrityError if the email is taken.
        """
        unknown = [r for r in roles if r not in ROLE_COLUMNS]
        if unknown:
            raise ValueError(f"Unknown role: {unknown[0]}")
        wanted = set(roles)
        cols = ", ".join(ROLE_COLUMNS.values())
        marks = ", ".join("?" * len(ROLE_COLUMNS))
        conn = self.db.connect()
        try:
            cur = conn.execute(
                f"INSERT INTO users (email, {cols}) VALUES (?, {marks})",
                [normalize_email(email)] + [1 if role in wanted else 0 for role in ROLE_COLUMNS],
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def get_by_email(self, email: str) -> Optional[sqlite3.Row]:
        return self.db.fetchone(f"SELECT {_COLUMNS} FROM users WHERE email = ?", (normalize_email(email),))

    def get_by_id(self, user_id: int) -> Optional[sqlite3.Row]:
        return self.db.fetchone(f"SELECT {_COLUMNS} FROM users WHERE id = ?", (user_id,))

    def list_all(self) -> list[sqlite3.Row]:
        return self.db.fetchall(f"SELECT {_COLUMNS} FROM users ORDER BY id")

    def list_with_role(self, *roles: str) -> list[sqlite3.Row]:
        """Users holding at least one of `roles`, oldest first."""
        unknown = [r for r in roles if r not in ROLE_COLUMNS]
        if unknown:
            raise ValueError(f"Unknown role: {unknown[0]}")
        cond = " OR ".join(f"{ROLE_COLUMNS[r]} = 1" for r in roles) or "0"
        return self.db.fetchall(f"SELECT {_COLUMNS} FROM users WHERE {cond} ORDER BY id")

    def set_admin(self, user_id: int, is_admin: bool) -> None:
        conn = self.db.connect()
        try:
            conn.execute(
                "UPDATE users SET is_admin = ? WHERE id = ?",
                (1 if is_admin else 0, int(user_id)),
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def roles_of(row) -> list[str]:
        """Role names held by a users row (in ROLE_COLUMNS order)."""
        keys = row.keys()
        return [role for role, col in ROLE_COLUMNS.items() if col in keys and bool(row[col])]

    def set_roles(self, user_id: int, roles: list[str]) -> None:
        """Set the user's roles to exactly `roles` (unknown names raise ValueError)."""
        unknown = [r for r in roles if r not in ROLE_COLUMNS]
        if unknown:
            raise ValueError(f"Unknown role: {unknown[0]}")
        wanted = set(roles)
        assignments = ", ".join(f"{col} = ?" for col in ROLE_COLUMNS.values())
        params = [1 if role in wanted else 0 for role in ROLE_COLUMNS] + [int(user_id)]
        conn = self.db.connect()
        try:
            conn.execute(f"UPDATE users SET {assignments} WHERE id = ?", params)
            conn.commit()
        finally:
            conn.close()
