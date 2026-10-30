"""
FILE:         app/ingestion/pipeline.py
WHAT IT DOES: THE INGESTION PIPELINE. Runs every document in the manifest through
              parse -> chunk -> register, and writes the chunks to disk.
WHERE IT FITS: Phase 4. Its output (data/processed/chunks.jsonl) is the input of
              Phase 5, which embeds the chunks and stores them in Qdrant.
USED BY:      scripts/ingest_documents.py (command line), tests; Phase 8's upload API.

For each document in manifest.yaml:
    STEP 1  fingerprint the file (sha256)
    STEP 2  parse it into elements             (parsers/)   - hidden content removed
    STEP 3  chunk it, stamping every chunk with its ACL     (chunker.py)
    STEP 4  record it in the `documents` table (new / changed / unchanged)
Then:
    STEP 5  write data/processed/chunks.jsonl  (one chunk per line)
    STEP 6  write data/processed/ingestion_report.json

Security choices:
    - A chunk's ACL comes ONLY from the manifest. A file that is not in the manifest is
      never ingested ("fail closed") - it is listed as unlisted in the report instead.
    - One broken file is reported as failed and skipped; it never stops the batch and
      never gets a default label.
"""

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import DATA_DIR
from app.ingestion.chunker import chunk_document
from app.ingestion.elements import ParsedDocument, TableBlock
from app.ingestion.manifest import DocumentEntry, load_manifest
from app.ingestion.models import DocumentRecord
from app.ingestion.parsers import parse_document
from app.ingestion.schemas import Chunk

logger = logging.getLogger(__name__)

RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
SUPPORTED_SUFFIXES = {".pdf", ".docx", ".xlsx"}


# =============================================================================
# 1. REPORT SHAPES - what happened to each document
# =============================================================================
@dataclass
class DocumentReport:
    doc_id: str
    status: str  # new | changed | unchanged | failed
    chunks: int = 0
    tables: int = 0
    hidden_removed: list[str] = field(default_factory=list)  # previews, for review
    error: str | None = None


@dataclass
class IngestionReport:
    documents: list[DocumentReport]
    chunks: list[Chunk]
    unlisted_files: list[str]  # files on disk with no manifest entry (NOT ingested)

    @property
    def failed(self) -> list[DocumentReport]:
        return [d for d in self.documents if d.status == "failed"]


# =============================================================================
# 2. THE PIPELINE
# =============================================================================
def ingest(
    manifest_path: Path = RAW_DIR / "manifest.yaml",
    out_dir: Path = PROCESSED_DIR,
    db: Session | None = None,
    keep_hidden: bool = False,
) -> IngestionReport:
    manifest = load_manifest(manifest_path)
    raw_dir = manifest_path.parent
    now = datetime.now(UTC)
    reports: list[DocumentReport] = []
    all_chunks: list[Chunk] = []

    for entry in manifest.documents:
        path = raw_dir / entry.path
        # STEP 1: fingerprint
        sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        try:
            # STEP 2 + 3: parse, then chunk with the manifest's ACL
            parsed = parse_document(path, entry.source_type, keep_hidden=keep_hidden)
            chunks = chunk_document(entry, parsed, sha256, now)
        except Exception as exc:  # noqa: BLE001 - one bad file must not stop the batch
            logger.exception("Failed to ingest %s", entry.doc_id)
            reports.append(DocumentReport(entry.doc_id, "failed", error=type(exc).__name__))
            continue

        if parsed.hidden_text:
            logger.warning("%s: removed %d hidden item(s)", entry.doc_id, len(parsed.hidden_text))

        # STEP 4: registry
        status = _register(db, entry, sha256, chunks, parsed, now) if db else "new"
        reports.append(DocumentReport(
            doc_id=entry.doc_id,
            status=status,
            chunks=len(chunks),
            tables=sum(isinstance(e, TableBlock) for e in parsed.elements),
            hidden_removed=[h[:80] for h in parsed.hidden_text],
        ))
        all_chunks.extend(chunks)

    if db is not None:
        db.commit()

    report = IngestionReport(reports, all_chunks, _unlisted_files(raw_dir, manifest.documents))
    _write_outputs(out_dir, report)  # STEP 5 + 6
    return report


# =============================================================================
# 3. HELPERS
# =============================================================================
# STEP 4: insert or update the document's registry row; return new/changed/unchanged.
def _register(
    db: Session, entry: DocumentEntry, sha256: str, chunks: list[Chunk],
    parsed: ParsedDocument, now: datetime,
) -> str:
    record = db.get(DocumentRecord, entry.doc_id)
    if record is None:
        status = "new"
        record = DocumentRecord(doc_id=entry.doc_id, first_ingested_at=now)
    else:
        status = "unchanged" if record.sha256 == sha256 else "changed"

    record.title, record.path, record.source_type = entry.title, entry.path, entry.source_type
    record.sha256 = sha256
    record.clearance_level = int(entry.clearance_level)
    record.departments = [str(d) for d in entry.departments]
    record.allowed_users = list(entry.allowed_users)
    record.denied_users = list(entry.denied_users)
    record.column_policies = [p.model_dump(mode="json") for p in entry.column_policies]
    record.contains_pii = entry.contains_pii
    record.chunk_count = len(chunks)
    record.hidden_items_removed = len(parsed.hidden_text)
    record.last_ingested_at = now
    db.add(record)
    return status


# Files present on disk that nobody gave an ACL to -> reported, never ingested.
def _unlisted_files(raw_dir: Path, entries: list[DocumentEntry]) -> list[str]:
    listed = {e.path for e in entries}
    on_disk = (
        p.relative_to(raw_dir).as_posix()
        for p in raw_dir.rglob("*")
        if p.suffix.lower() in SUPPORTED_SUFFIXES
    )
    return sorted(path for path in on_disk if path not in listed)


# STEP 5 + 6: chunks as JSON Lines (easy to inspect, easy for Phase 5 to stream).
def _write_outputs(out_dir: Path, report: IngestionReport) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "chunks.jsonl").open("w", encoding="utf-8") as f:
        for chunk in report.chunks:
            f.write(chunk.model_dump_json() + "\n")
    summary = {
        "documents": [asdict(d) for d in report.documents],
        "total_chunks": len(report.chunks),
        "unlisted_files": report.unlisted_files,
    }
    (out_dir / "ingestion_report.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
