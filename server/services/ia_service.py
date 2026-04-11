
import asyncio
import logging
import requests
from typing import Iterator, Optional

logger = logging.getLogger(__name__)


class InternetArchiveService:
    def __init__(self, collection: str):
        self.collection = collection

    def iter_collection_movies(self, rows: int = 100) -> Iterator[dict]:
        page = 1
        while True:
            payload = self._advancedsearch(page=page, rows=rows)
            docs = (payload.get("response") or {}).get("docs") or []
            if not docs:
                return
            for d in docs:
                yield d
            num_found = (payload.get("response") or {}).get("numFound") or 0
            if page * rows >= num_found or len(docs) < rows:
                return
            page += 1

    def sync_collection(self, films_repo, rows: int = 100, max_pages: Optional[int] = None, workers: int = 20, force: bool = False) -> int:
        """Fetch movie docs from Internet Archive and upsert them into the films table.

        Uses asyncio + aiohttp for non-blocking concurrent description fetches.
        workers: max concurrent requests (semaphore limit).
        force: if True, re-fetch descriptions even for films already in DB.
        Returns number of films inserted/updated.
        """
        # Collect all docs first
        all_docs: list[dict] = []
        for d in self.iter_collection_movies(rows=rows):
            all_docs.append(d)
            if max_pages is not None and len(all_docs) >= max_pages * rows:
                break

        if not all_docs:
            return 0

        # Decide which films need a metadata fetch BEFORE upserting, so that
        # films with only a search-API description (plain, run-on) are still
        # treated as needing enrichment on first sync.
        identifiers = [d.get("identifier") for d in all_docs if d.get("identifier")]
        if force:
            need_desc = set(identifiers)
            print(f"  Force mode: re-fetching descriptions for all {len(need_desc)} films...")
        else:
            need_desc = films_repo.get_identifiers_without_description(identifiers)

        # Upsert with search-API data first so all films exist in DB
        films_repo.upsert_many_from_ia(all_docs)

        if not need_desc:
            print(f"  All {len(identifiers)} films already have descriptions — skipping metadata fetch.")
            return len(all_docs)

        if not force:
            print(f"  Fetching descriptions for {len(need_desc)} new films "
                  f"({len(identifiers) - len(need_desc)} already cached)...")

        # Fetch concurrently with asyncio
        html_map = asyncio.run(self._fetch_all_descriptions(list(need_desc), workers))

        # Upsert again with enriched descriptions
        enriched = [
            dict(d, description=html_map[d["identifier"]], description_is_html=True)
            if d.get("identifier") in html_map else d
            for d in all_docs
        ]
        films_repo.upsert_many_from_ia(enriched)
        return len(all_docs)

    async def _fetch_all_descriptions(self, identifiers: list[str], workers: int) -> dict[str, str]:
        """Fetch HTML descriptions for all identifiers concurrently using aiohttp."""
        try:
            import aiohttp
        except ImportError:
            logger.warning("aiohttp not installed — falling back to threaded fetches. "
                           "Run: pip install aiohttp")
            return self._fetch_all_descriptions_threaded(identifiers, workers)

        sem = asyncio.Semaphore(workers)
        results: dict[str, str] = {}
        done = 0
        total = len(identifiers)

        async def fetch_one(session: aiohttp.ClientSession, ident: str) -> None:
            nonlocal done
            url = f"https://archive.org/metadata/{ident}/metadata/description"
            async with sem:
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        resp.raise_for_status()
                        data = await resp.json(content_type=None)
                        result = data.get("result")
                        if isinstance(result, str) and result.strip():
                            results[ident] = result
                except Exception as e:
                    logger.warning("fetch_description_html failed for %s: %s", ident, e)
                finally:
                    done += 1
                    if done % 10 == 0 or done == total:
                        print(f"  Descriptions: {done}/{total}", flush=True)

        connector = aiohttp.TCPConnector(limit=workers)
        async with aiohttp.ClientSession(connector=connector) as session:
            await asyncio.gather(*(fetch_one(session, ident) for ident in identifiers))

        return results

    def _fetch_all_descriptions_threaded(self, identifiers: list[str], workers: int) -> dict[str, str]:
        """Fallback threaded fetch if aiohttp is unavailable."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        html_map: dict[str, str] = {}
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_id = {
                executor.submit(self.fetch_description_html, ident): ident
                for ident in identifiers
            }
            for future in as_completed(future_to_id):
                ident = future_to_id[future]
                done += 1
                try:
                    result = future.result()
                    if result:
                        html_map[ident] = result
                    if done % 10 == 0 or done == len(identifiers):
                        print(f"  Descriptions: {done}/{len(identifiers)}", flush=True)
                except Exception as e:
                    logger.warning("fetch failed for %s: %s", ident, e)
        return html_map

    def fetch_description_html(self, identifier: str) -> Optional[str]:
        """Fetch the HTML description from the metadata API (sync). Returns None on failure."""
        url = f"https://archive.org/metadata/{identifier}/metadata/description"
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            data = r.json()
            result = data.get("result")
            if isinstance(result, str) and result.strip():
                return result
            return None
        except Exception as e:
            logger.warning("fetch_description_html failed for %s: %s", identifier, e)
            return None

    def _advancedsearch(self, page: int, rows: int) -> dict:
        q = f"collection:{self.collection} AND mediatype:movies"
        url = "https://archive.org/advancedsearch.php"
        params = {
            "q": q,
            "fl[]": ["identifier", "title", "description"],
            "rows": rows,
            "page": page,
            "output": "json",
        }
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json()
