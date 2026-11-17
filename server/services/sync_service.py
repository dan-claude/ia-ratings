"""Runs the Internet Archive collection sync in a background thread.

A sync can take minutes, so the admin API starts it and returns immediately;
the client polls `status()` to show progress. State lives in this process
only, which is fine because production runs a single gunicorn worker (see
CLAUDE.md) — it resets on restart.
"""
import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)


def _now() -> float:
    return time.time()


class SyncService:
    def __init__(self, ia, films):
        self.ia = ia
        self.films = films
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._status = self._blank_status()

    @staticmethod
    def _blank_status() -> dict:
        return {
            "state": "idle",        # idle | running | done | error
            "phase": None,          # listing | descriptions (while running)
            "done": 0,
            "total": None,
            "synced": None,         # films fetched by the last finished sync
            "error": None,
            "started_at": None,     # unix seconds
            "finished_at": None,
        }

    def status(self) -> dict:
        with self._lock:
            return dict(self._status)

    def is_running(self) -> bool:
        with self._lock:
            return self._status["state"] == "running"

    def start(self) -> bool:
        """Start a sync in the background. Returns False if one is already running."""
        with self._lock:
            if self._status["state"] == "running":
                return False
            self._status = self._blank_status()
            self._status.update(state="running", phase="listing", started_at=_now())
            self._thread = threading.Thread(target=self._run, name="ia-sync", daemon=True)
            self._thread.start()
            return True

    def wait(self, timeout: Optional[float] = None) -> None:
        """Block until the current sync finishes (used by tests)."""
        t = self._thread
        if t is not None:
            t.join(timeout)

    # -- internals ---------------------------------------------------------

    def _progress(self, phase: str, done: int, total: Optional[int]) -> None:
        with self._lock:
            self._status.update(phase=phase, done=done, total=total)

    def _run(self) -> None:
        try:
            synced = self.ia.sync_collection(self.films, progress=self._progress)
        except Exception as exc:  # noqa: BLE001 — surface any failure to the admin UI
            logger.exception("sync.failed")
            with self._lock:
                self._status.update(
                    state="error", phase=None, error=str(exc) or exc.__class__.__name__, finished_at=_now()
                )
            return
        with self._lock:
            self._status.update(state="done", phase=None, synced=synced, finished_at=_now())
