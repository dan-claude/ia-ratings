import sqlite3
from typing import Optional
from ..db import Database

class CriteriaRepository:
    def __init__(self, db: Database):
        self.db = db

    def list_active(self) -> list[sqlite3.Row]:
        return self.db.fetchall(
            "SELECT id, key, label, min_score, max_score, sort_order, active "
            "FROM criteria WHERE active=1 ORDER BY sort_order"
        )

    def list_all(self) -> list[sqlite3.Row]:
        return self.db.fetchall(
            "SELECT id, key, label, min_score, max_score, sort_order, active "
            "FROM criteria ORDER BY sort_order"
        )

    def get_by_id(self, cid: int) -> Optional[sqlite3.Row]:
        return self.db.fetchone("SELECT * FROM criteria WHERE id=?", (cid,))

    def insert(self, key: str, label: str, min_score: int, max_score: int, sort_order: int, active: int) -> None:
        conn = self.db.connect()
        try:
            conn.execute(
                "INSERT INTO criteria (key,label,min_score,max_score,sort_order,active) VALUES (?,?,?,?,?,?)",
                (key, label, min_score, max_score, sort_order, active),
            )
            conn.commit()
        finally:
            conn.close()

    def update(self, cid: int, label: str, min_score: int, max_score: int, sort_order: int, active: int) -> None:
        conn = self.db.connect()
        try:
            conn.execute(
                "UPDATE criteria SET label=?, min_score=?, max_score=?, sort_order=?, active=? WHERE id=?",
                (label, min_score, max_score, sort_order, active, cid),
            )
            conn.commit()
        finally:
            conn.close()
