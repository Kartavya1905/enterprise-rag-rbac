"""
FILE:         app/api/health.py
WHAT IT DOES: Two URLs that report whether the service is healthy.
                GET /health        -> "is the process alive?"   (always 200 if running)
                GET /health/ready  -> "can it do its job?"      (200 or 503)
WHERE IT FITS: Phase 1 - foundation. Docker, Kubernetes and cloud hosts call these to
              decide whether to send traffic to the service or restart it.
USED BY:      main.py registers the router; tests/unit/test_health.py tests it.
"""

import logging

from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy import text

from app.core.database import get_engine
from app.core.vectorstore import get_qdrant_client

logger = logging.getLogger(__name__)

# All routes in this file start with /health.
router = APIRouter(prefix="/health", tags=["health"])


# =============================================================================
# 1. RESPONSE SHAPES - what the JSON reply looks like
# =============================================================================
class ComponentStatus(BaseModel):
    ok: bool
    detail: str | None = None  # error type when ok is False, e.g. "ConnectionError"


class ReadinessResponse(BaseModel):
    status: str  # "ready" or "degraded"
    components: dict[str, ComponentStatus]  # {"database": ..., "vectorstore": ...}


# =============================================================================
# 2. COMPONENT CHECKS - each one pings one dependency
# =============================================================================
def check_database() -> ComponentStatus:
    try:
        # Cheapest possible query: proves we can connect and run SQL.
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return ComponentStatus(ok=True)
    except Exception as exc:  # noqa: BLE001 - report any failure as unhealthy
        logger.warning("Database health check failed: %s", exc)
        # Only the error TYPE is returned, never the message (it may contain addresses).
        return ComponentStatus(ok=False, detail=type(exc).__name__)


def check_vectorstore() -> ComponentStatus:
    try:
        # Listing collections proves Qdrant is reachable and answering.
        get_qdrant_client().get_collections()
        return ComponentStatus(ok=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Vector store health check failed: %s", exc)
        return ComponentStatus(ok=False, detail=type(exc).__name__)


# =============================================================================
# 3. THE ROUTES
# =============================================================================
# GET /health - liveness: if this code runs at all, the process is alive.
@router.get("")
def liveness() -> dict[str, str]:
    return {"status": "ok"}


# GET /health/ready - readiness: run every check; any failure -> HTTP 503.
@router.get("/ready", response_model=ReadinessResponse)
def readiness(response: Response) -> ReadinessResponse:
    components = {"database": check_database(), "vectorstore": check_vectorstore()}
    ready = all(c.ok for c in components.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="ready" if ready else "degraded", components=components)
