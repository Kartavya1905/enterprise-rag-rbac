"""
FILE:         app/core/vectorstore.py
WHAT IT DOES: Creates the connection to Qdrant, the vector database that will store
              document chunks (as embeddings) together with their access labels.
WHERE IT FITS: Phase 1 - foundation. Used heavily from Phase 5 (indexing) and Phase 6
              (access-filtered search).
USED BY:      api/health.py (readiness check), main.py (closes it on shutdown).

Three modes, chosen by settings:
    QDRANT_URL set           -> remote Qdrant server (Docker)
    QDRANT_PATH = ":memory:" -> temporary in-memory Qdrant (tests)
    otherwise                -> embedded Qdrant saved to disk at data/qdrant (local dev)
"""

from functools import lru_cache
from pathlib import Path

from qdrant_client import QdrantClient

from app.core.config import get_settings


@lru_cache  # one shared client for the whole app
def get_qdrant_client() -> QdrantClient:
    settings = get_settings()

    # --- Mode 1: remote server (docker compose runs one at http://qdrant:6333) ---
    if settings.qdrant_is_remote:
        api_key = settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None
        return QdrantClient(url=settings.qdrant_url, api_key=api_key)

    # --- Mode 2: in-memory (data vanishes when the process ends) ---
    if settings.qdrant_path == ":memory:":
        return QdrantClient(location=":memory:")

    # --- Mode 3: embedded, saved to a local folder ---
    Path(settings.qdrant_path).mkdir(parents=True, exist_ok=True)
    return QdrantClient(path=settings.qdrant_path)
