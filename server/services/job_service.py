"""Runs long admin jobs (the title lookup after a CSV import)
in a background thread, one at a time.

A job can take minutes, so the admin API starts it and returns immediately;
the client polls `status()` to show progress. State lives in this process
only, which is fine because production runs a single gunicorn worker (see
CLAUDE.md) — it resets on restart.
"""
import logging
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)


def _now() -> float:
    return time.time()


class JobService:
    def __init__(self):
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._status = self._blank_status()

    @staticmethod
    def _blank_status() -> dict:
        return {
            "state": "idle",        # idle | running | done | error
            "kind": None,           # which job this status is about (currently only "titles")
            "phase": None,          # titles (while running)
            "done": 0,
            "total": None,
            "processed": None,      # items processed by the last finished job (titles found)
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

    def start_job(
        self,
        kind: str,
        fn: Callable[[Callable[[str, int, Optional[int]], None]], int],
        first_phase: Optional[str] = None,
    ) -> bool:
        """Run fn(progress) in the background; fn returns the number of items processed.

        Returns False (and does nothing) if another job is already running.
        """
        with self._lock:
            if self._status["state"] == "running":
                return False
            self._status = self._blank_status()
            self._status.update(state="running", kind=kind, phase=first_phase or kind, started_at=_now())
            self._thread = threading.Thread(target=self._run, args=(fn,), name=f"job-{kind}", daemon=True)
            self._thread.start()
            return True

    def wait(self, timeout: Optional[float] = None) -> None:
        """Block until the current job finishes (used by tests)."""
        t = self._thread
        if t is not None:
            t.join(timeout)

    # -- internals ---------------------------------------------------------

    def _progress(self, phase: str, done: int, total: Optional[int]) -> None:
        with self._lock:
            self._status.update(phase=phase, done=done, total=total)

    def _run(self, fn) -> None:
        try:
            processed = fn(self._progress)
        except Exception as exc:  # noqa: BLE001 — surface any failure to the admin UI
            logger.exception("job.failed")
            with self._lock:
                self._status.update(
                    state="error", phase=None, error=str(exc) or exc.__class__.__name__, finished_at=_now()
                )
            return
        with self._lock:
            self._status.update(state="done", phase=None, processed=processed, finished_at=_now())
