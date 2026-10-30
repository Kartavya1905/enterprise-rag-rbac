"""
FILE:         app/api/search.py
WHAT IT DOES: POST /search - the logged-in user's question in, the most relevant chunks
              THEY are allowed to read out. No LLM yet (that is Phase 7).
WHERE IT FITS: Phase 6. Lets you see exactly what the retriever would hand the LLM, per
              user - the best way to demonstrate (and test) the access control.
USED BY:      main.py registers the router; tests/unit/test_search_api.py.

Existence-leak protection: when nothing readable matches, every user gets the SAME
neutral message. The API never says "that document exists but is restricted".
"""

import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.audit import service as audit
from app.auth.dependencies import CurrentUser
from app.core.rate_limit import limit_per_user
from app.retrieval.embeddings import Embedder, get_embedder
from app.retrieval.reranker import Reranker, get_reranker
from app.retrieval.search import MAX_QUERY_CHARS, SearchUnavailable, search

router = APIRouter(tags=["search"])

NO_RESULTS_MESSAGE = "No matching information found in the documents you have access to."


# =============================================================================
# 1. REQUEST / RESPONSE SHAPES
# =============================================================================
# The request has ONLY the question and a result count - no user, role or clearance
# field. Who is asking comes exclusively from the verified token (CurrentUser).
class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    top_k: int = Field(default=5, ge=1, le=10)


# What a client sees per result: content + where it came from. Deliberately NOT included:
# allowed_users / denied_users (they would reveal other people's access).
class SearchResultItem(BaseModel):
    doc_title: str
    section: str | None
    page: int | None
    sheet: str | None
    classification: str
    text: str
    score: float


class SearchResponse(BaseModel):
    results: list[SearchResultItem]
    message: str | None = None


# =============================================================================
# 2. THE ROUTE
# =============================================================================
@router.post("/search", response_model=SearchResponse,
             dependencies=[Depends(limit_per_user("search"))])
def search_documents(
    body: SearchRequest,
    request: Request,
    user: CurrentUser,  # STEP 1: verified identity (401 if missing/invalid)
    embedder: Annotated[Embedder, Depends(get_embedder)],
    reranker: Annotated[Reranker, Depends(get_reranker)],
) -> SearchResponse:
    # STEP 2: secure search - filtered by THIS user's access, double-checked, reranked
    started = time.perf_counter()
    try:
        result = search(user, body.query, embedder=embedder, reranker=reranker,
                        top_k=body.top_k)
    except SearchUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    # AUDIT (Phase 9): which documents this user's search touched.
    audit.record(
        "search", outcome="blocked" if result.blocked else ("ok" if result.hits else
                                                           "no_results"),
        user=user, request=request, question=body.query,
        retrieved_doc_ids=[h.doc_id for h in result.hits],
        flags=["acl_double_check_blocked"] if result.blocked else [],
        latency_ms=round((time.perf_counter() - started) * 1000),
    )

    # STEP 3: shape the response; same neutral message whenever nothing is found
    items = [
        SearchResultItem(
            doc_title=h.doc_title, section=h.section, page=h.page, sheet=h.sheet,
            classification=h.classification, text=h.text, score=round(h.score, 4),
        )
        for h in result.hits
    ]
    return SearchResponse(results=items, message=None if items else NO_RESULTS_MESSAGE)
