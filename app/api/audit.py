"""
FILE:         app/api/audit.py
WHAT IT DOES: Read-only access to the audit log - admins only.
                GET /admin/audit          recent events, filterable
                GET /admin/audit/stats    summary: volumes, security signals, latency
                GET /admin/audit/verify   has the log been tampered with?
WHERE IT FITS: Phase 9. Phase 10's dashboard reads these.
USED BY:      main.py registers the router; tests/unit/test_audit.py.

There is deliberately NO endpoint to edit or delete audit events. Viewing the log is
itself audited ("audit_view"), and events that touched documents the viewer may not read
are masked (see app/audit/service.py).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import select

from app.audit import service as audit
from app.audit.models import AuditEvent
from app.auth.dependencies import AdminUser
from app.core.database import DbSession
from app.core.rate_limit import limit_per_user

router = APIRouter(prefix="/admin/audit", tags=["audit"],
                   dependencies=[Depends(limit_per_user("admin"))])


class AuditEventView(BaseModel):
    id: int
    timestamp: str
    event_type: str
    outcome: str
    user_id: str | None
    role: str | None
    client_ip: str | None
    request_id: str | None
    question: str | None
    retrieved_doc_ids: list[str]
    cited_doc_ids: list[str]
    flags: list[str]
    latency_ms: int | None
    timings: dict
    detail: dict


class VerifyResponse(BaseModel):
    ok: bool
    checked: int
    first_bad_id: int | None


# =============================================================================
# ROUTES
# =============================================================================
@router.get("", response_model=list[AuditEventView])
def list_events(
    request: Request,
    admin: AdminUser,
    db: DbSession,
    event_type: str | None = None,
    user_id: str | None = None,
    outcome: str | None = None,
    since: Annotated[str | None, Query(description="ISO time, e.g. 2026-10-29T00:00")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict]:
    # --- STEP 1: filter, newest first ---
    stmt = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit)
    if event_type:
        stmt = stmt.where(AuditEvent.event_type == event_type)
    if user_id:
        stmt = stmt.where(AuditEvent.user_id == user_id)
    if outcome:
        stmt = stmt.where(AuditEvent.outcome == outcome)
    if since:
        stmt = stmt.where(AuditEvent.timestamp >= since)
    events = list(db.scalars(stmt))

    # --- STEP 2: mask what this admin may not see ---
    readable = audit.readable_doc_ids(db, admin)
    views = [audit.visible_view(e, readable) for e in events]

    # --- STEP 3: watching the log is itself logged ---
    audit.record("audit_view", outcome="ok", user=admin, request=request,
                 detail={"filters": {"event_type": event_type, "user_id": user_id,
                                     "outcome": outcome, "since": since},
                         "returned": len(views)})
    return views


@router.get("/stats")
def stats(admin: AdminUser, db: DbSession,
          hours: Annotated[int, Query(ge=1, le=24 * 90)] = 24) -> dict:
    return audit.compute_stats(db, admin, hours)


@router.get("/verify", response_model=VerifyResponse)
def verify(admin: AdminUser, db: DbSession) -> audit.ChainReport:
    return audit.verify_chain(db)
