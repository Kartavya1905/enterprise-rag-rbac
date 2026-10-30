"""
FILE:         scripts/ingest_documents.py
WHAT IT DOES: Runs the ingestion pipeline from the command line and prints a summary.
WHERE IT FITS: Phase 4. Run after generating the dataset (and again whenever documents
              or their ACLs change).
USED BY:      you.

    python -m scripts.ingest_documents                                   # local SQLite
    python -m scripts.ingest_documents --database-url postgresql+psycopg://rag:rag_dev_password@localhost:5432/enterprise_rag

Outputs:
    data/processed/chunks.jsonl            every chunk with its text + access label
    data/processed/ingestion_report.json   per-document results
    `documents` table                      the registry (new / changed / unchanged)
"""

import argparse
import os
import sys

from app.core.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse, chunk and register all documents.")
    parser.add_argument("--database-url", help="override DATABASE_URL (e.g. Docker Postgres)")
    parser.add_argument("--keep-hidden", action="store_true",
                        help="DANGEROUS: keep hidden text (for investigation only)")
    args = parser.parse_args()

    # Point the app's settings at the chosen database BEFORE anything connects.
    if args.database_url:
        os.environ["DATABASE_URL"] = args.database_url
        get_settings.cache_clear()

    from app.core.database import get_session_factory, init_db
    from app.ingestion.pipeline import PROCESSED_DIR, ingest

    init_db()
    with get_session_factory()() as db:
        report = ingest(db=db, keep_hidden=args.keep_hidden)

    # --- summary table ---
    print(f"{'document':<34} {'status':<10} {'chunks':>6} {'tables':>6}  hidden removed")
    for d in report.documents:
        hidden = ""
        if d.hidden_removed:
            hidden = f"{len(d.hidden_removed)}: {d.hidden_removed[0][:40]}..."
        print(f"{d.doc_id:<34} {d.status:<10} {d.chunks:>6} {d.tables:>6}  {hidden}")
    print(f"\n{len(report.chunks)} chunks written to {PROCESSED_DIR / 'chunks.jsonl'}")
    if report.unlisted_files:
        print(f"NOT ingested (no manifest entry): {report.unlisted_files}")
    if report.failed:
        print(f"FAILED: {[d.doc_id for d in report.failed]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
