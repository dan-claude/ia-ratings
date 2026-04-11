
import sqlite3
from typing import Optional

from ..db import Database


class UserRepository:
    def __init__(self, db: Database):
        self.db = db

    def create_user(self, email: str, password_hash: str) -> int:
        conn = self.db.connect()
        try:
            cur = conn.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                (email, password_hash),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def get_by_email(self, email: str) -> Optional[sqlite3.Row]:
        return self.db.fetchone(
            "SELECT id, email, password_hash, is_admin, created_at FROM users WHERE email = ?",
            (email,),
        )

    def get_by_id(self, user_id: int) -> Optional[sqlite3.Row]:
        return self.db.fetchone(
            "SELECT id, email, is_admin, created_at FROM users WHERE id = ?",
            (user_id,),
        )

    def get_by_ia_username(self, ia_username: str) -> Optional[sqlite3.Row]:
        return self.db.fetchone(
            "SELECT id, email, is_admin, created_at FROM users WHERE ia_username = ?",
            (ia_username,),
        )

    def create_ia_user(self, ia_username: str) -> int:
        conn = self.db.connect()
        try:
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, ia_username) VALUES (?, 'IA_AUTH', ?)",
                (f"{ia_username}@users.archive.org", ia_username),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

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
