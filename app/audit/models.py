"""
FILE:         app/audit/models.py
WHAT IT DOES: The `audit_events` table - a permanent, append-only record of who did what:
              every question, search, login, admin change and security event.
WHERE IT FITS: Phase 9. Written by app/audit/service.py; read by GET /admin/audit.
USED BY:      audit/service.py, core/database.py (init_db creates the table).

TAMPER EVIDENCE (a "hash chain", the idea behind blockchains):
    each row stores   prev_hash = the previous row's row_hash
                      row_hash  = SHA-256(prev_hash + this row's contents)
    Editing or deleting ANY past row breaks every hash after it, so
    GET /admin/audit/verify can prove whether the log was altered.

    row 1: hash(GENESIS + data1) = A
    row 2: hash(A + data2)       = B      change data1 -> A changes -> B no longer matches
    row 3: hash(B + data3)       = C
"""

from sqlalchemy import JSON, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # --- when / what ---
    # ISO-8601 UTC text ("2026-10-29T04:44:20.831000Z"): sorts correctly as text and
    # round-trips byte-for-byte, which the hash chain needs.
    timestamp: Mapped[str] = mapped_column(String(32), index=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)  # query, login, ...
    outcome: Mapped[str] = mapped_column(String(32), index=True)  # ok, refused, denied ...

    # --- who / from where ---
    user_id: Mapped[str | None] = mapped_column(String(64), index=True)
    role: Mapped[str | None] = mapped_column(String(32))
    client_ip: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(64))

    # --- the question and what it touched (answers themselves are NOT stored) ---
    question: Mapped[str | None] = mapped_column(Text)  # sensitive ids already masked
    retrieved_doc_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    cited_doc_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    flags: Mapped[list[str]] = mapped_column(JSON, default=list)  # security signals

    # --- performance ---
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    timings: Mapped[dict] = mapped_column(JSON, default=dict)  # e.g. {"search_ms": 210}

    # --- extra details (admin changes, attempted login name, ...) ---
    detail: Mapped[dict] = mapped_column(JSON, default=dict)

    # --- tamper evidence ---
    prev_hash: Mapped[str] = mapped_column(String(64))
    row_hash: Mapped[str] = mapped_column(String(64), unique=True)
