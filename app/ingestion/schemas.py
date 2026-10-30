"""
FILE:         app/ingestion/schemas.py
WHAT IT DOES: The shape of a CHUNK - a small piece of a document plus its access label
              and metadata. Chunks are the unit that gets searched and sent to the LLM.
WHERE IT FITS: Phase 4 produces chunks; Phase 5 stores them in Qdrant (text -> vector,
              everything else -> searchable "payload"); Phase 6 filters on the label.
USED BY:      ingestion/chunker.py, ingestion/pipeline.py, tests.

Because Chunk inherits ResourceACL, `can_read(user, chunk)` works directly - the same
oracle that decides document access decides chunk access.
"""

from datetime import datetime

from app.core.access import ResourceACL
from app.ingestion.manifest import SourceType


class Chunk(ResourceACL):
    # --- inherited access label (from ResourceACL) ---
    #   clearance_level, departments, allowed_users, denied_users

    # --- identity ---
    chunk_id: str  # deterministic UUID: same doc version + position -> same id
    doc_id: str
    chunk_index: int  # position within the document (0, 1, 2 ...)

    # --- where it came from ---
    doc_title: str
    source_type: SourceType
    source_path: str
    section: str | None = None  # e.g. "1. Time Off" or "Severity levels > SEV1"
    page: int | None = None  # PDF page (1-based)
    sheet: str | None = None  # spreadsheet worksheet name
    columns: list[str] | None = None  # spreadsheet columns included in this chunk

    # --- the content ---
    # A context header ("[Document: ... | Section: ...]") + the body text. This full
    # string is what gets embedded and what the LLM sees, so even a chunk read on its own
    # says which document and section it belongs to.
    text: str
    token_estimate: int

    # --- sensitivity and versioning ---
    classification: str  # public / internal / confidential / restricted
    contains_pii: bool
    doc_sha256: str  # fingerprint of the source file version
    ingested_at: datetime
