"""
FILE:         app/audit/service.py
WHAT IT DOES: Writes audit events, verifies the hash chain, and prepares the log for
              viewing - with masking, so the audit log can't become a side channel.
WHERE IT FITS: Phase 9. Every endpoint calls record(); /admin/audit reads through here.
USED BY:      api/*, core/rate_limit.py, ingestion/admin.py, api/audit.py, tests.

    record()        append one event (masks sensitive ids, extends the hash chain)
    verify_chain()  recompute every hash - was anything edited or deleted?
    visible_view()  an event as a given viewer may see it (MASKING, below)
    compute_stats() counts, security signals, top documents, latency

MASKING - "who watches the watchers":
    The admin (clearance 3, engineering) reviews the log. If the CEO asked about the
    layoff plan, the question text alone would reveal that the plan exists. So when an
    event touched a document the VIEWER may not read, its question text and those
    document ids are hidden from that viewer.

Recording never breaks a request: if the audit write fails, the failure is logged loudly
and the user still gets their answer.
"""

import hashlib
import json
import logging
import threading
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.models import AuditEvent
from app.core.access import Principal, ResourceACL, can_read
from app.core.database import get_session_factory
from app.ingestion.models import DocumentRecord
from app.security.redaction import redact

logger = logging.getLogger(__name__)

GENESIS = "0" * 64  # prev_hash of the very first event
HIDDEN = "[hidden]"  # shown instead of text the viewer may not see
_chain_lock = threading.Lock()  # one writer at a time keeps the chain unbroken

# The fields covered by the hash (everything except id and the hash columns).
_HASHED = ["timestamp", "event_type", "outcome", "user_id", "role", "client_ip",
           "request_id", "question", "retrieved_doc_ids", "cited_doc_ids", "flags",
           "latency_ms", "timings", "detail"]


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _hash(prev_hash: str, fields: dict) -> str:
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256((prev_hash + canonical).encode()).hexdigest()


# =============================================================================
# 1. RECORD AN EVENT
# =============================================================================
def record(
    event_type: str,
    *,
    outcome: str,
    user: Principal | None = None,
    user_id: str | None = None,
    role: str | None = None,
    request: Request | None = None,
    question: str | None = None,
    retrieved_doc_ids: list[str] | None = None,
    cited_doc_ids: list[str] | None = None,
    flags: list[str] | None = None,
    latency_ms: int | None = None,
    timings: dict | None = None,
    detail: dict | None = None,
) -> None:
    fields = {
        "timestamp": _now(),
        "event_type": event_type,
        "outcome": outcome,
        "user_id": user.user_id if user else user_id,
        "role": getattr(user, "role", None) or role,
        "client_ip": request.client.host if request and request.client else None,
        "request_id": getattr(request.state, "request_id", None) if request else None,
        # Questions are stored with tax IDs / account numbers masked (data minimisation).
        "question": redact(question).text if question else None,
        "retrieved_doc_ids": sorted(set(retrieved_doc_ids or [])),
        "cited_doc_ids": sorted(set(cited_doc_ids or [])),
        "flags": list(flags or []),
        "latency_ms": latency_ms,
        "timings": {k: int(v) for k, v in (timings or {}).items()},
        "detail": detail or {},
    }
    try:
        with _chain_lock, get_session_factory()() as db:
            last = db.scalars(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(1)).first()
            prev_hash = last.row_hash if last else GENESIS
            db.add(AuditEvent(**fields, prev_hash=prev_hash, row_hash=_hash(prev_hash, fields)))
            db.commit()
    except Exception:  # noqa: BLE001 - never fail the user's request because of the log
        logger.critical("AUDIT WRITE FAILED for %s/%s", event_type, fields["user_id"],
                        exc_info=True)


# =============================================================================
# 2. VERIFY THE CHAIN - detects edited, deleted or reordered rows
# =============================================================================
@dataclass
class ChainReport:
    ok: bool
    checked: int
    first_bad_id: int | None = None


def verify_chain(db: Session) -> ChainReport:
    prev_hash, checked = GENESIS, 0
    for event in db.scalars(select(AuditEvent).order_by(AuditEvent.id)):
        fields = {name: getattr(event, name) for name in _HASHED}
        if event.prev_hash != prev_hash or event.row_hash != _hash(prev_hash, fields):
            return ChainReport(False, checked, event.id)
        prev_hash = event.row_hash
        checked += 1
    return ChainReport(True, checked)


# =============================================================================
# 3. VIEWING WITH MASKING
# =============================================================================
def readable_doc_ids(db: Session, viewer: Principal) -> set[str]:
    """Documents (by id) the viewer may read, per the registry's current labels."""
    return {
        d.doc_id for d in db.scalars(select(DocumentRecord))
        if can_read(viewer, ResourceACL(clearance_level=d.clearance_level,
                                        departments=d.departments,
                                        allowed_users=d.allowed_users,
                                        denied_users=d.denied_users))
    }


def visible_view(event: AuditEvent, readable: set[str]) -> dict:
    """The event as the viewer may see it. Unknown/removed documents count as unreadable."""
    touched = set(event.retrieved_doc_ids) | set(event.cited_doc_ids)
    hidden_docs = touched - readable

    def mask(ids: list[str]) -> list[str]:
        return [i if i in readable else HIDDEN for i in ids]

    return {
        "id": event.id, "timestamp": event.timestamp, "event_type": event.event_type,
        "outcome": event.outcome, "user_id": event.user_id, "role": event.role,
        "client_ip": event.client_ip, "request_id": event.request_id,
        # If ANY touched document is off-limits to the viewer, hide the question too.
        "question": HIDDEN if (hidden_docs and event.question) else event.question,
        "retrieved_doc_ids": mask(event.retrieved_doc_ids),
        "cited_doc_ids": mask(event.cited_doc_ids),
        "flags": event.flags, "latency_ms": event.latency_ms, "timings": event.timings,
        "detail": event.detail,
    }


# =============================================================================
# 4. STATISTICS for a time window
# =============================================================================
SECURITY_OUTCOMES = {"refused", "blocked", "denied", "rate_limited", "failed"}


def compute_stats(db: Session, viewer: Principal, hours: int) -> dict:
    since = (datetime.now(UTC) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    events = list(db.scalars(select(AuditEvent).where(AuditEvent.timestamp >= since)))
    readable = readable_doc_ids(db, viewer)
    queries = [e for e in events if e.event_type == "query"]
    latencies = sorted(e.latency_ms for e in queries if e.latency_ms is not None)

    top_docs = Counter(d if d in readable else HIDDEN
                       for e in queries for d in e.retrieved_doc_ids)
    return {
        "window_hours": hours,
        "total_events": len(events),
        "by_event_type": dict(Counter(e.event_type for e in events)),
        "by_outcome": dict(Counter(e.outcome for e in events)),
        "queries_by_role": dict(Counter(e.role for e in queries)),
        "security": {
            "flagged_events": sum(e.outcome in SECURITY_OUTCOMES for e in events),
            "injections_refused": sum(any(f.startswith("input_injection") for f in e.flags)
                                      for e in events),
            "poisoned_chunks_dropped": sum(any(f.startswith("context_injection")
                                               for f in e.flags) for e in events),
            "failed_logins": sum(e.event_type == "login" and e.outcome == "failed"
                                 for e in events),
            "rate_limited": sum(e.outcome == "rate_limited" for e in events),
            "self_grants_blocked": sum(e.event_type == "admin" and e.outcome == "denied"
                                       for e in events),
        },
        "top_documents": [{"doc_id": d, "retrievals": n} for d, n in top_docs.most_common(10)],
        "query_latency_ms": {
            "count": len(latencies),
            "avg": round(sum(latencies) / len(latencies)) if latencies else None,
            "p95": latencies[max(0, round(0.95 * len(latencies)) - 1)] if latencies else None,
        },
    }
