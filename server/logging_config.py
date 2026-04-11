"""Logging configuration for the Flask server.

- Logs to stdout (good for local dev + containers)
- Timestamps, level, logger name
- Controlled via LOG_LEVEL (default INFO)
"""

from __future__ import annotations

import logging
import os
import sys


def configure_logging() -> None:
    """Configure Python logging for the server process."""
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    if root.handlers:
        root.setLevel(level)
        return

    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    handler.setFormatter(formatter)

    root.setLevel(level)
    root.addHandler(handler)
    logging.getLogger("werkzeug").setLevel(level)
