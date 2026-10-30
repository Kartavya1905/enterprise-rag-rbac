"""
FILE:         app/main.py
WHAT IT DOES: Builds the FastAPI web application - the program that answers HTTP requests.
              This is the entry point: `uvicorn app.main:app --reload` starts it.
WHERE IT FITS: Phase 1 - foundation. Every later route (login, query, ingest, admin) gets
              plugged in here with `app.include_router(...)`.
USED BY:      uvicorn (locally), the Dockerfile's CMD (in Docker), and the tests.

Lifecycle:  create_app()  ->  lifespan STARTUP  ->  serve requests  ->  lifespan SHUTDOWN
"""

import logging
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.admin import router as admin_router
from app.api.audit import router as audit_router
from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.query import router as query_router
from app.api.search import router as search_router
from app.core.config import DATA_DIR, get_settings
from app.core.database import init_db
from app.core.logging import configure_logging
from app.core.vectorstore import get_qdrant_client

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).parent / "web"  # the browser UI (Phase 10)


# =============================================================================
# 1. STARTUP AND SHUTDOWN - code that runs once when the server starts / stops
# =============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # ---------- STARTUP ----------
    settings = get_settings()
    configure_logging(settings.log_level)
    DATA_DIR.mkdir(parents=True, exist_ok=True)  # make sure data/ exists
    init_db()  # create the users tables if they don't exist yet (Phase 3)
    logger.info(
        "Starting %s v%s (env=%s, qdrant=%s)",
        settings.app_name,
        __version__,
        settings.environment,
        "remote" if settings.qdrant_is_remote else "embedded",
    )

    yield  # <- the server handles requests while paused here

    # ---------- SHUTDOWN ----------
    # Embedded Qdrant holds a file lock; release it cleanly on shutdown.
    get_qdrant_client().close()


# =============================================================================
# 2. SECURITY HEADERS - added to every response (Phase 8)
# =============================================================================
# Answers contain confidential text, so browsers and proxies must never cache them;
# the other headers stop the API being framed or content-sniffed by a browser.
SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


# Content Security Policy (Phase 10): the browser may only load scripts, styles and data
# from THIS server - no inline scripts, no third-party code, no framing. Even if some text
# slipped into the page as HTML, an injected <script> would not run.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; "
    "form-action 'self'; frame-ancestors 'none'"
)
# FastAPI's developer pages load their scripts from a CDN, so they are left out.
_CSP_EXEMPT = ("/docs", "/redoc", "/openapi.json")

_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")


async def add_security_headers(request: Request, call_next):
    # Request ID (Phase 9): reuse a well-formed incoming X-Request-ID (e.g. from a proxy)
    # or make one. It is returned to the caller AND stored in the audit log, so one
    # complaint ("my request at 10:42 failed") can be traced to the exact audit row.
    incoming = request.headers.get("x-request-id", "")
    request.state.request_id = incoming if _SAFE_REQUEST_ID.match(incoming) else uuid.uuid4().hex

    response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if not request.url.path.startswith(_CSP_EXEMPT):
        response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


# =============================================================================
# 3. BUILD THE APP - create FastAPI and register all routes
# =============================================================================
def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version=__version__, lifespan=lifespan)
    app.middleware("http")(add_security_headers)

    # --- Routes ---
    app.include_router(health_router)  # GET /health, GET /health/ready
    app.include_router(auth_router)  # POST /auth/login, GET /auth/me   (Phase 3)
    app.include_router(search_router)  # POST /search                   (Phase 6)
    app.include_router(query_router)  # POST /query - LLM answers       (Phase 7)
    app.include_router(admin_router)  # /admin/* - document management  (Phase 8)
    app.include_router(audit_router)  # /admin/audit* - the audit log    (Phase 9)

    # --- Web UI (Phase 10): static files from app/web, served at /app/ ---
    app.mount("/app", StaticFiles(directory=WEB_DIR, html=True), name="web")

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/app/")

    return app


# =============================================================================
# 4. THE APP OBJECT - what uvicorn imports and runs
# =============================================================================
app = create_app()
