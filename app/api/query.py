"""
FILE:         app/api/query.py
WHAT IT DOES: POST /query - the main feature: ask a question, get an answer written by the
              local LLM from ONLY the documents you may read, with citations.
WHERE IT FITS: Phase 7; rate limited per user since Phase 8.

Why no word-by-word streaming: the output guard (canary, redaction, citation checks) needs
the COMPLETE answer before anything is shown. Streaming would send words before they were
checked. With answers taking ~1-2 s on the GPU, safety wins over streaming.
USED BY:      main.py registers the router; tests/unit/test_query_api.py.

Internal security flags (blocked injections, redactions) are logged, never returned -
telling an attacker exactly which check fired would help them tune the next attempt.
"""

import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.audit import service as audit
from app.auth.dependencies import CurrentUser
from app.core.rate_limit import limit_per_user
from app.generation.answer import answer_question
from app.generation.llm import LLM, LLMUnavailable, get_llm
from app.retrieval.embeddings import Embedder, get_embedder
from app.retrieval.reranker import Reranker, get_reranker
from app.retrieval.search import MAX_QUERY_CHARS, SearchUnavailable

router = APIRouter(tags=["query"])


# Only the question - who is asking comes from the verified token (CurrentUser).
class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)


class SourceItem(BaseModel):
    id: str  # "S1" - matches [S1] in the answer text
    doc_title: str
    location: str


class QueryResponse(BaseModel):
    answer: str
    citations: list[SourceItem]  # sources the answer cites
    sources: list[SourceItem]  # all sources the answer was based on


@router.post("/query", response_model=QueryResponse,
             dependencies=[Depends(limit_per_user("query"))])  # each call runs the LLM
def query(
    body: QueryRequest,
    request: Request,
    user: CurrentUser,
    embedder: Annotated[Embedder, Depends(get_embedder)],
    reranker: Annotated[Reranker, Depends(get_reranker)],
    llm: Annotated[LLM, Depends(get_llm)],
) -> QueryResponse:
    started = time.perf_counter()
    try:
        result = answer_question(user, body.question, embedder=embedder,
                                 reranker=reranker, llm=llm)
    except (SearchUnavailable, LLMUnavailable, ValueError) as exc:
        audit.record("query", outcome="error", user=user, request=request,
                     question=body.question, flags=[f"error:{type(exc).__name__}"])
        if isinstance(exc, ValueError):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "The answer service is temporarily unavailable.") from exc

    # AUDIT (Phase 9): who asked what, which documents were used, what fired, how long.
    # The answer text itself is NOT stored - it may contain confidential content.
    audit.record(
        "query", outcome=result.outcome, user=user, request=request,
        question=body.question, retrieved_doc_ids=result.retrieved_doc_ids,
        cited_doc_ids=result.cited_doc_ids, flags=result.flags,
        latency_ms=round((time.perf_counter() - started) * 1000), timings=result.timings,
    )

    def items(refs):
        return [SourceItem(id=r.source_id, doc_title=r.doc_title, location=r.location)
                for r in refs]

    return QueryResponse(answer=result.text, citations=items(result.citations),
                         sources=items(result.sources))
