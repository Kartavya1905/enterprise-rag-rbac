"""
FILE:         app/ingestion/admin.py
WHAT IT DOES: Document administration: upload a new document, change a document's access
              label (ACL), remove a document, rebuild everything.
WHERE IT FITS: Phase 8. Called by the /admin API routes.
USED BY:      api/admin.py, tests.

Every change follows the same safe recipe:
    STEP 1  validate the change (same rules as the manifest loader, incl. combine_acls)
    STEP 2  security checks (admins cannot grant THEMSELVES access; file type is real)
    STEP 3  write manifest.yaml atomically (temp file + rename: never half-written)
    STEP 4  rebuild: ingest (Phase 4) -> index (Phase 5). Thanks to the fingerprints only
            the changed document is re-embedded; an ACL change reaches Qdrant at once.
    STEP 5  on failure, put the old manifest back and rebuild again (roll back)

manifest.yaml stays the single source of truth for access labels. One lock serialises
changes, so two admins editing at the same moment cannot overwrite each other.
Removing a document takes it out of the manifest and the index but leaves the file on
disk: an unlisted file is never ingested (fail closed), and nothing is destroyed.
"""

import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from app.core.access import Principal, can_read
from app.core.config import get_settings
from app.ingestion.manifest import DocumentEntry, Manifest
from app.ingestion.models import DocumentRecord
from app.ingestion.pipeline import IngestionReport, ingest
from app.retrieval.embeddings import Embedder
from app.retrieval.indexer import IndexReport, index_chunks

audit_log = logging.getLogger("audit")
_lock = threading.Lock()

# Real files start with these bytes ("magic numbers"), whatever their name claims.
_MAGIC = {"pdf": b"%PDF-", "docx": b"PK\x03\x04", "xlsx": b"PK\x03\x04"}


# =============================================================================
# 1. ERRORS - each maps to one HTTP status in api/admin.py
# =============================================================================
class DocumentNotFound(LookupError): ...          # 404
class DocumentConflict(ValueError): ...           # 409
class SelfGrantForbidden(PermissionError): ...    # 403
class InvalidDocument(ValueError): ...            # 422


@dataclass
class RebuildResult:
    ingestion: IngestionReport
    index: IndexReport


# =============================================================================
# 2. MANIFEST FILE HELPERS
# =============================================================================
def _paths() -> tuple[Path, Path, Path]:
    s = get_settings()
    raw = Path(s.documents_dir)
    return raw, raw / "manifest.yaml", Path(s.processed_dir)


def _read_manifest() -> dict:
    _, manifest_path, _ = _paths()
    return yaml.safe_load(manifest_path.read_text(encoding="utf-8"))


# STEP 3: validate the WHOLE manifest, then swap the file in one atomic rename.
def _write_manifest(data: dict) -> None:
    Manifest.model_validate(data)  # raises on any invalid entry - nothing written
    _, manifest_path, _ = _paths()
    tmp = manifest_path.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    os.replace(tmp, manifest_path)


def _find(data: dict, doc_id: str) -> dict:
    for entry in data["documents"]:
        if entry["doc_id"] == doc_id:
            return entry
    raise DocumentNotFound(doc_id)


# =============================================================================
# 3. REBUILD - ingest everything, index what changed (STEP 4)
# =============================================================================
def rebuild(db: Session, embedder: Embedder) -> RebuildResult:
    _, manifest_path, processed = _paths()
    report = ingest(manifest_path, out_dir=processed, db=db)
    return RebuildResult(report, index_chunks(report.chunks, embedder=embedder))


# Apply a manifest change; if the rebuild fails, restore the previous manifest (STEP 5).
def _apply(new_data: dict, db: Session, embedder: Embedder) -> RebuildResult:
    old_data = _read_manifest()
    _write_manifest(new_data)
    try:
        return rebuild(db, embedder)
    except Exception:
        db.rollback()
        _write_manifest(old_data)
        rebuild(db, embedder)
        raise


# =============================================================================
# 4. CHANGE A DOCUMENT'S ACCESS LABEL
# =============================================================================
ACL_FIELDS = {"clearance_level", "departments", "allowed_users", "denied_users"}


def update_acl(db: Session, embedder: Embedder, admin: Principal, doc_id: str,
               changes: dict) -> DocumentEntry:
    if not changes or set(changes) - ACL_FIELDS:
        raise InvalidDocument(f"only {sorted(ACL_FIELDS)} can be changed")
    with _lock:
        data = _read_manifest()
        entry = _find(data, doc_id)

        # STEP 1: build + validate the new label
        old = DocumentEntry.model_validate(entry)
        try:
            new = DocumentEntry.model_validate(entry | changes)
        except ValueError as exc:
            raise InvalidDocument(_first_error(exc)) from exc

        # STEP 2: an admin may manage labels, but never to open a document to THEMSELVES
        if can_read(admin, new) and not can_read(admin, old):
            audit_log.warning("SELF-GRANT BLOCKED: %s tried to grant themselves %s",
                              admin.user_id, doc_id)
            raise SelfGrantForbidden("administrators cannot grant themselves access")

        entry.update(new.model_dump(mode="json", include=ACL_FIELDS))
        _apply(data, db, embedder)  # STEP 3-5
    audit_log.info("ACL CHANGED by %s on %s: %s", admin.user_id, doc_id, changes)
    return new


# =============================================================================
# 5. UPLOAD A NEW DOCUMENT
# =============================================================================
def add_document(db: Session, embedder: Embedder, admin: Principal, *, filename: str,
                 content: bytes, doc_id: str, title: str, clearance_level: int,
                 departments: list[str], allowed_users: list[str], denied_users: list[str],
                 contains_pii: bool) -> DocumentEntry:
    # STEP 2a: the file must really be what its extension says
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext not in _MAGIC:
        raise InvalidDocument("only .pdf, .docx and .xlsx files are accepted")
    if not content.startswith(_MAGIC[ext]):
        raise InvalidDocument(f"file content is not a valid .{ext}")

    # STEP 1: validate the new entry. doc_id must match ^[a-z0-9-]+$, so it can never
    # contain "../" - the stored filename is built from it, not from the upload's name.
    entry = {
        "doc_id": doc_id, "path": f"uploads/{doc_id}.{ext}", "title": title,
        "source_type": ext, "owner": admin.user_id, "clearance_level": clearance_level,
        "departments": departments, "allowed_users": allowed_users,
        "denied_users": denied_users, "contains_pii": contains_pii,
    }
    try:
        DocumentEntry.model_validate(entry)
    except ValueError as exc:
        raise InvalidDocument(_first_error(exc)) from exc

    raw, _, _ = _paths()
    target = raw / entry["path"]
    with _lock:
        data = _read_manifest()
        if any(e["doc_id"] == doc_id for e in data["documents"]) or target.exists():
            raise DocumentConflict(f"document '{doc_id}' already exists")

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        data["documents"].append(entry)
        try:
            result = _apply(data, db, embedder)
            failed = {d.doc_id for d in result.ingestion.failed}
            if doc_id in failed:  # unreadable file: undo everything
                raise InvalidDocument("the file could not be parsed")
        except Exception:
            data["documents"].remove(entry)
            _write_manifest(data)
            target.unlink(missing_ok=True)  # our own just-written file
            rebuild(db, embedder)
            raise
    audit_log.info("DOCUMENT ADDED by %s: %s (clearance %s, %s)", admin.user_id, doc_id,
                   clearance_level, departments)
    return DocumentEntry.model_validate(entry)


# =============================================================================
# 6. REMOVE A DOCUMENT (from manifest + index; the file itself is kept)
# =============================================================================
def remove_document(db: Session, embedder: Embedder, admin: Principal, doc_id: str) -> None:
    with _lock:
        data = _read_manifest()
        data["documents"].remove(_find(data, doc_id))
        if not data["documents"]:
            raise DocumentConflict("cannot remove the last document")
        _apply(data, db, embedder)
        record = db.get(DocumentRecord, doc_id)
        if record is not None:
            db.delete(record)
            db.commit()
    audit_log.info("DOCUMENT REMOVED by %s: %s", admin.user_id, doc_id)


def _first_error(exc: Exception) -> str:
    errors = getattr(exc, "errors", None)
    if callable(errors):
        first = errors()[0]
        return f"{'.'.join(str(p) for p in first['loc'])}: {first['msg']}".strip(": ")
    return str(exc)
