import logging
import requests
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class InternetArchiveService:
    """Reads film titles from archive.org (the spreadsheet has no title column)."""

    def fetch_title(self, identifier: str) -> Optional[str]:
        """Fetch an item's title from the metadata API. Returns None on failure/absence."""
        url = f"https://archive.org/metadata/{identifier}/metadata/title"
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            result = r.json().get("result")
            if isinstance(result, list):
                result = result[0] if result else None
            if isinstance(result, str) and result.strip():
                return result.strip()
            return None
        except Exception as e:
            logger.warning("fetch_title failed for %s: %s", identifier, e)
            return None

    def fetch_titles(
        self,
        identifiers: list[str],
        workers: int = 10,
        progress: Optional[Callable[[str, int, Optional[int]], None]] = None,
    ) -> dict[str, str]:
        """Look up titles for many items concurrently. Items without a title are omitted."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        titles: dict[str, str] = {}
        total = len(identifiers)
        if progress:
            progress("titles", 0, total)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(self.fetch_title, ident): ident for ident in identifiers}
            for done, future in enumerate(as_completed(futures), 1):
                title = future.result()
                if title:
                    titles[futures[future]] = title
                if progress:
                    progress("titles", done, total)
        return titles
