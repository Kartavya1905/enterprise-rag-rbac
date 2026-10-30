"""
FILE:         app/core/logging.py
WHAT IT DOES: Sets the format and level of log messages printed by the app.
WHERE IT FITS: Phase 1 - foundation. Called once when the API starts (main.py).
USED BY:      main.py (and later, command-line scripts).

Example log line:
    2026-10-29 00:40:30,379 INFO     app.main: Starting Enterprise RAG (RBAC) v0.1.0
"""

import logging


def configure_logging(level: str = "INFO") -> None:
    # Format: time, level, which module logged it, the message.
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    # Qdrant/httpx are noisy at INFO.
    logging.getLogger("httpx").setLevel(logging.WARNING)
