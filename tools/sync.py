#!/usr/bin/env python3
"""
tools/sync.py

Run a collection sync from the command line with configurable concurrency.

Usage (from repo root):
    python tools/sync.py                        # smart: only fetch missing descriptions
    python tools/sync.py --workers 20           # more threads, faster first sync
    python tools/sync.py --workers 1            # fully sequential, gentlest on IA
    python tools/sync.py --force                # re-fetch ALL descriptions (e.g. after a normalization fix)
    python tools/sync.py --db server/app.db --workers 10

Options:
    --db PATH       Path to SQLite DB (default: server/app.db)
    --workers N     Concurrent metadata fetch threads (default: 10)
    --collection C  IA collection slug (default: from config)
    --force         Re-fetch descriptions even for films that already have one
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from server.config import load_settings
from server.db import Database
from server.repositories.film_repo import FilmRepository
from server.services.ia_service import InternetArchiveService


def main(argv: list[str] | None = None) -> int:
    settings = load_settings()

    parser = argparse.ArgumentParser(description="Sync IA collection to local DB")
    parser.add_argument(
        "--db",
        default=os.environ.get("DB_PATH", str(repo_root / "server" / "app.db")),
        help="Path to SQLite DB (default: server/app.db)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=10,
        help="Concurrent metadata fetch threads (default: 10)",
    )
    parser.add_argument(
        "--collection",
        default=settings.collection,
        help=f"IA collection slug (default: {settings.collection})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-fetch descriptions for all films, even ones already in DB",
    )
    args = parser.parse_args(argv)

    print(f"DB:         {args.db}")
    print(f"Collection: {args.collection}")
    print(f"Workers:    {args.workers}")
    print(f"Force:      {args.force}")
    print()

    db = Database(args.db)
    films_repo = FilmRepository(db, args.collection)
    ia = InternetArchiveService(args.collection)

    print("Fetching film list from Internet Archive...")
    total = ia.sync_collection(films_repo, workers=args.workers, force=args.force)
    print(f"\nDone. {total} films synced.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
