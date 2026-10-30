"""
FILE:         scripts/index_chunks.py
WHAT IT DOES: Loads data/processed/chunks.jsonl (from Phase 4) into Qdrant.
WHERE IT FITS: Phase 5. Run after `python -m scripts.ingest_documents`.
USED BY:      you.

    python -m scripts.index_chunks                                   # embedded Qdrant
    python -m scripts.index_chunks --qdrant-url http://localhost:6333   # Docker Qdrant
    python -m scripts.index_chunks --recreate        # rebuild from scratch (model change)

First run downloads the two embedding models (~65 MB) into data/models/.
"""

import argparse
import os
import time
from pathlib import Path

from app.core.config import DATA_DIR, get_settings

CHUNKS_PATH = DATA_DIR / "processed" / "chunks.jsonl"


def main() -> None:
    parser = argparse.ArgumentParser(description="Embed chunks and index them in Qdrant.")
    parser.add_argument("--qdrant-url", help="override QDRANT_URL (e.g. Docker Qdrant)")
    parser.add_argument("--chunks", type=Path, default=CHUNKS_PATH)
    parser.add_argument("--recreate", action="store_true",
                        help="delete and rebuild the collection")
    args = parser.parse_args()

    # Point settings at the chosen Qdrant BEFORE anything connects.
    if args.qdrant_url:
        os.environ["QDRANT_URL"] = args.qdrant_url
        get_settings.cache_clear()

    from app.ingestion.schemas import Chunk
    from app.retrieval.indexer import index_chunks

    # --- STEP 1: read the chunks produced by Phase 4 ---
    lines = args.chunks.read_text(encoding="utf-8").splitlines()
    chunks = [Chunk.model_validate_json(line) for line in lines if line.strip()]
    print(f"Loaded {len(chunks)} chunks from {args.chunks}")

    # --- STEP 2: embed + upload (only changed documents) ---
    started = time.perf_counter()
    report = index_chunks(chunks, recreate=args.recreate)
    elapsed = time.perf_counter() - started

    # --- STEP 3: summary ---
    print(f"\n{'document':<34} {'status':<10} {'points':>6}")
    for d in report.documents:
        print(f"{d.doc_id:<34} {d.status:<10} {d.points:>6}")
    if report.removed_docs:
        print(f"\nRemoved from index: {report.removed_docs}")
    indexed = sum(d.status == "indexed" for d in report.documents)
    print(f"\n{indexed} document(s) (re)indexed in {elapsed:.1f}s; "
          f"collection '{get_settings().qdrant_collection}' now holds {report.total_points} points")


if __name__ == "__main__":
    main()
