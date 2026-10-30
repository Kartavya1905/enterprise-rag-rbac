"""
FILE:         app/api/admin.py
WHAT IT DOES: Document administration over HTTP - admins only.
                GET    /admin/documents                 list documents + their ACLs
                POST   /admin/documents                 upload a new document (+ ACL)
                PATCH  /admin/documents/{doc_id}/acl    change who may read a document
                DELETE /admin/documents/{doc_id}        remove a document from search
                POST   /admin/reindex                   rebuild everything
WHERE IT FITS: Phase 8. The business logic lives in app/ingestion/admin.py.
USED BY:      main.py registers the router; tests/unit/test_admin_api.py.

Every route requires role "admin" (from the database - AdminUser) and is rate limited.
Admin rights never widen what the admin can READ through /search or /query.
"""

from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field

from app.audit import service as audit
from app.auth.dependencies import AdminUser
from app.core.config import get_settings
from app.core.database import DbSession
from app.core.rate_limit import limit_per_user
from app.ingestion import admin as service
from app.ingestion.models import DocumentRecord
from app.retrieval.embeddings import Embedder, get_embedder

router = APIRouter(prefix="/admin", tags=["admin"],
                   dependencies=[Depends(limit_per_user("admin"))])

EmbedderDep = Annotated[Embedder, Depends(get_embedder)]


# =============================================================================
# 1. SHAPES
# =============================================================================
class DocumentSummary(BaseModel):
    doc_id: str
    title: str
    source_type: str
    clearance_level: int
    departments: list[str]
    allowed_users: list[str]
    denied_users: list[str]
    contains_pii: bool
    chunk_count: int
    hidden_items_removed: int


# Every field optional: send only what changes. Unknown fields are rejected.
class AclUpdate(BaseModel, extra="forbid"):
    clearance_level: int | None = Field(default=None, ge=1, le=4)
    departments: list[str] | None = None
    allowed_users: list[str] | None = None
    denied_users: list[str] | None = None


class ReindexSummary(BaseModel):
    documents: int
    chunks: int
    reindexed: list[str]
    removed: list[str]


# =============================================================================
# 2. ERROR MAPPING - service exceptions -> HTTP status codes
# =============================================================================
def _http_error(exc: Exception) -> HTTPException:
    code = {
        service.DocumentNotFound: status.HTTP_404_NOT_FOUND,
        service.DocumentConflict: status.HTTP_409_CONFLICT,
        service.SelfGrantForbidden: status.HTTP_403_FORBIDDEN,
        service.InvalidDocument: status.HTTP_422_UNPROCESSABLE_CONTENT,
    }[type(exc)]
    detail = "document not found" if code == 404 else str(exc)
    return HTTPException(code, detail)


_SERVICE_ERRORS = (service.DocumentNotFound, service.DocumentConflict,
                   service.SelfGrantForbidden, service.InvalidDocument)


def _csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


# AUDIT (Phase 9): every admin action, successful or not. A blocked self-grant is
# recorded with outcome "denied" so it shows up in the security statistics.
def _audit_admin(request: Request, admin, detail: dict, error: Exception | None = None) -> None:
    if error is None:
        outcome = "ok"
    elif isinstance(error, service.SelfGrantForbidden):
        outcome = "denied"
    else:
        outcome = "rejected"
    audit.record("admin", outcome=outcome, user=admin, request=request,
                 detail=detail | ({"error": type(error).__name__} if error else {}))


# =============================================================================
# 3. ROUTES
# =============================================================================
@router.get("/documents", response_model=list[DocumentSummary])
def list_documents(admin: AdminUser, db: DbSession) -> list[DocumentRecord]:
    return sorted(db.query(DocumentRecord).all(), key=lambda d: (d.clearance_level, d.doc_id))


# Multipart form: the file plus its access label. Lists are comma-separated.
@router.post("/documents", response_model=DocumentSummary, status_code=201)
def upload_document(
    request: Request,
    admin: AdminUser,
    db: DbSession,
    embedder: EmbedderDep,
    file: Annotated[UploadFile, File()],
    doc_id: Annotated[str, Form()],
    title: Annotated[str, Form()],
    clearance_level: Annotated[int, Form(ge=1, le=4)],
    departments: Annotated[str, Form(description="comma-separated, e.g. hr,finance")],
    allowed_users: Annotated[str, Form()] = "",
    denied_users: Annotated[str, Form()] = "",
    contains_pii: Annotated[bool, Form()] = False,
) -> DocumentRecord:
    # Read at most the size limit + 1 byte - never load an oversized upload fully.
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    content = file.file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "file too large")
    detail = {"action": "upload", "doc_id": doc_id, "clearance_level": clearance_level,
              "departments": _csv(departments)}
    try:
        service.add_document(
            db, embedder, admin, filename=file.filename or "", content=content,
            doc_id=doc_id, title=title, clearance_level=clearance_level,
            departments=_csv(departments), allowed_users=_csv(allowed_users),
            denied_users=_csv(denied_users), contains_pii=contains_pii,
        )
    except _SERVICE_ERRORS as exc:
        _audit_admin(request, admin, detail, exc)
        raise _http_error(exc) from exc
    _audit_admin(request, admin, detail)
    return db.get(DocumentRecord, doc_id)


@router.patch("/documents/{doc_id}/acl", response_model=DocumentSummary)
def update_acl(doc_id: str, body: AclUpdate, request: Request, admin: AdminUser,
               db: DbSession, embedder: EmbedderDep) -> DocumentRecord:
    changes = body.model_dump(exclude_none=True)
    detail = {"action": "acl_change", "doc_id": doc_id, "changes": changes}
    try:
        service.update_acl(db, embedder, admin, doc_id, changes)
    except _SERVICE_ERRORS as exc:
        _audit_admin(request, admin, detail, exc)
        raise _http_error(exc) from exc
    _audit_admin(request, admin, detail)
    return db.get(DocumentRecord, doc_id)


@router.delete("/documents/{doc_id}", status_code=204)
def delete_document(doc_id: str, request: Request, admin: AdminUser, db: DbSession,
                    embedder: EmbedderDep) -> Response:
    detail = {"action": "remove", "doc_id": doc_id}
    try:
        service.remove_document(db, embedder, admin, doc_id)
    except _SERVICE_ERRORS as exc:
        _audit_admin(request, admin, detail, exc)
        raise _http_error(exc) from exc
    _audit_admin(request, admin, detail)
    return Response(status_code=204)


@router.post("/reindex", response_model=ReindexSummary)
def reindex(request: Request, admin: AdminUser, db: DbSession,
            embedder: EmbedderDep) -> ReindexSummary:
    result = service.rebuild(db, embedder)
    _audit_admin(request, admin, {"action": "reindex"})
    return ReindexSummary(
        documents=len(result.ingestion.documents),
        chunks=len(result.ingestion.chunks),
        reindexed=[d.doc_id for d in result.index.documents if d.status == "indexed"],
        removed=result.index.removed_docs,
    )
