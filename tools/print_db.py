#!/usr/bin/env python3
"""Query the IA Ratings SQLite database and print results."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterable

# Let `python tools/print_db.py` import the server package (--invite reuses its code).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

def _default_db_path() -> str:
    server_dir = Path(__file__).resolve().parent.parent / "server"
    return os.environ.get("DB_PATH", str(server_dir / "app.db"))

def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def _list_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """SELECT name FROM sqlite_master
             WHERE type='table' AND name NOT LIKE 'sqlite_%'
             ORDER BY name"""
    ).fetchall()
    return [r[0] for r in rows]

def _row_count(conn: sqlite3.Connection, table: str) -> int:
    row = conn.execute(f"SELECT COUNT(1) AS n FROM {table}").fetchone()
    return int(row["n"]) if row and row["n"] is not None else 0

def _fetch_rows(
    conn: sqlite3.Connection,
    table: str,
    where: str | None,
    limit: int | None,
    offset: int | None,
    order_by: str | None,
) -> list[sqlite3.Row]:
    sql = f"SELECT * FROM {table}"
    params: list[Any] = []
    if where:
        sql += f" WHERE {where}"
    if order_by:
        sql += f" ORDER BY {order_by}"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))
    if offset is not None:
        sql += " OFFSET ?"
        params.append(int(offset))
    return conn.execute(sql, params).fetchall()

def _rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [{k: r[k] for k in r.keys()} for r in rows]

def _print_table(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("(no rows)")
        return
    cols = list(rows[0].keys())
    widths = {c: len(c) for c in cols}
    for row in rows:
        for c in cols:
            s = "" if row.get(c) is None else str(row.get(c))
            widths[c] = max(widths[c], len(s))

    def fmt(row: dict[str, Any]) -> str:
        return " | ".join(("" if row.get(c) is None else str(row.get(c))).ljust(widths[c]) for c in cols)

    print(fmt({c: c for c in cols}))
    print("-+-".join("-" * widths[c] for c in cols))
    for r in rows:
        print(fmt(r))

def _invite(db_path: str, email: str, roles: list[str], days: int) -> int:
    """Create the user if needed (or add roles to an existing one), issue a fresh magic link, print it."""
    from datetime import datetime, timedelta, timezone

    from server.config import load_settings
    from server.db import Database
    from server.repositories.login_link_repo import LoginLinkRepository
    from server.repositories.session_repo import SessionRepository
    from server.repositories.user_repo import UserRepository
    from server.services.login_link_service import LoginLinkService

    users = UserRepository(Database(db_path))
    db = users.db
    svc = LoginLinkService(users, LoginLinkRepository(db), SessionRepository(db))
    expires = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        row = users.get_by_email(email)
        if row is None:
            res = svc.invite(email, roles, expires)
            link, uid, verb = res["link"], res["user_id"], "Created"
        else:
            uid = int(row["id"])
            merged = list(dict.fromkeys([*UserRepository.roles_of(row), *roles]))
            users.set_roles(uid, merged)
            link, verb = svc.reissue(uid, expires), "Updated"
    except (ValueError, KeyError, LookupError) as exc:
        print(f"Error: {exc.args[0] if exc.args else exc}", file=sys.stderr)
        return 2
    roles_now = UserRepository.roles_of(users.get_by_id(uid))
    print(f"{verb} {email.strip().lower()} (id={uid}, roles: {', '.join(roles_now) or 'none'}).")
    base = load_settings().public_url.rstrip("/")
    if base:
        print(f"Sign-in link (valid until {link['expires_at']}; shown only now):\n{base}{link['path']}")
    else:
        print(f"Sign-in link path (valid until {link['expires_at']}; shown only now): {link['path']}")
        print("Set PUBLIC_URL (e.g. https://your-site.example) to print the full address; put it in front of that path.")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Query the IA Ratings SQLite DB and print results.")
    p.add_argument("--db", default=_default_db_path(), help="Path to SQLite db (default: %(default)s)")
    p.add_argument("--tables", action="store_true", help="List tables and row counts (default if no --table)")
    p.add_argument("--table", help="Table to dump (e.g. users, films, assignments, ratings, rating_scores)")
    p.add_argument("--where", help='Optional SQL WHERE clause (e.g. "user_id=1")')
    p.add_argument("--order-by", dest="order_by", help='Optional SQL ORDER BY clause (e.g. "id DESC")')
    p.add_argument("--limit", type=int, help="Limit rows")
    p.add_argument("--offset", type=int, help="Offset rows")
    p.add_argument("--json", action="store_true", help="Output as JSON (array of objects)")
    p.add_argument("--schema", action="store_true", help="Print CREATE TABLE statements for user tables")
    p.add_argument("--make-admin", metavar="EMAIL", help="Set is_admin=1 for the given user email (CLI-only)")
    p.add_argument("--revoke-admin", metavar="EMAIL", help="Set is_admin=0 for the given user email (CLI-only)")
    p.add_argument("--invite", metavar="EMAIL", help="Create the user (or re-issue their link) and print a magic sign-in link")
    p.add_argument("--admin", action="store_true", help="With --invite: give the user the admin role")
    p.add_argument("--roles", default="", help="With --invite: comma-separated roles to give (admin, reviewer, judge)")
    p.add_argument("--days", type=int, default=30, help="With --invite: days until the link expires (default: %(default)s)")
    args = p.parse_args(argv)

    db_path = args.db
    if not args.invite and not os.path.exists(db_path):  # --invite may create a fresh database
        print(f"DB not found: {db_path}", file=sys.stderr)
        print("Tip: set DB_PATH to point at your db file, or run the server once to create it.", file=sys.stderr)
        return 2

    if args.invite:
        roles = [r.strip() for r in args.roles.split(",") if r.strip()]
        if args.admin and "admin" not in roles:
            roles.append("admin")
        return _invite(db_path, args.invite, roles, args.days)

    conn = _connect(db_path)
    try:
        tables = _list_tables(conn)

        if args.make_admin or args.revoke_admin:
            email = (args.make_admin or args.revoke_admin).strip().lower()
            is_admin = bool(args.make_admin)
            row = conn.execute("SELECT id, email FROM users WHERE email = ?", (email,)).fetchone()
            if not row:
                print(f"User not found: {email}", file=sys.stderr)
                return 2
            conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (1 if is_admin else 0, int(row["id"])))
            conn.commit()
            print(f"Set is_admin={1 if is_admin else 0} for {row['email']} (id={row['id']})")
            return 0

        if args.schema:
            for t in tables:
                row = conn.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                    (t,),
                ).fetchone()
                sql = row["sql"] if row else None
                print((sql.strip() + ";\n") if sql else f"-- no schema for {t}\n")
            return 0

        if args.table:
            if args.table not in tables:
                print(f"Unknown table: {args.table}", file=sys.stderr)
                print(f"Known tables: {', '.join(tables)}", file=sys.stderr)
                return 2
            rows = _fetch_rows(conn, args.table, args.where, args.limit, args.offset, args.order_by)
            dicts = _rows_to_dicts(rows)
            if args.json:
                print(json.dumps(dicts, indent=2, ensure_ascii=False))
            else:
                _print_table(dicts)
            return 0

        for t in tables:
            print(f"{t}: {_row_count(conn, t)} rows")
        return 0
    finally:
        conn.close()

if __name__ == "__main__":
    raise SystemExit(main())
