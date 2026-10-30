"""
FILE:         app/retrieval/search.py
WHAT IT DOES: THE SECURE SEARCH. Given a verified user and a question, returns the most
              relevant chunks THAT USER IS ALLOWED TO READ - nothing else.
WHERE IT FITS: Phase 6. Phase 7 feeds these results to the LLM; POST /search exposes
              them directly.
USED BY:      api/search.py, (Phase 7) the answer generator, tests.

    STEP 1  validate the question
    STEP 2  build the access filter from the user        (acl_filter.py)
    STEP 3  embed the question: dense + sparse           (embeddings.py)
    STEP 4  hybrid search in Qdrant - the filter is applied to BOTH the dense and the
            sparse search, then results are fused (RRF)
    STEP 5  DOUBLE-CHECK every result with can_read()    (defense in depth)
            -> any violation = security alert + return NOTHING (fail closed)
    STEP 6  rerank the survivors, keep the top_k         (reranker.py)

Why STEP 5 if STEP 4 already filtered? If the filter ever had a bug (or the index held
a wrongly-labelled point), this is the last line before content reaches the user.
"""

import logging
from dataclasses import dataclass, replace

from pydantic import ValidationError
from qdrant_client import QdrantClient, models

from app.core.access import Principal, ResourceACL, can_read
from app.core.config import get_settings
from app.core.vectorstore import get_qdrant_client
from app.retrieval.acl_filter import build_acl_filter
from app.retrieval.collection import DENSE, SPARSE
from app.retrieval.embeddings import Embedder
from app.retrieval.reranker import Reranker

logger = logging.getLogger(__name__)
security_log = logging.getLogger("security")  # alerts go to a dedicated logger

MAX_QUERY_CHARS = 1000


class SearchUnavailable(RuntimeError):
    """The search index does not exist yet (nothing has been indexed)."""


# =============================================================================
# 1. RESULT SHAPES - only what the caller needs; no ACL user lists are exposed
# =============================================================================
@dataclass(frozen=True)
class SearchHit:
    chunk_id: str
    doc_id: str
    doc_title: str
    section: str | None
    page: int | None
    sheet: str | None
    classification: str
    text: str
    score: float  # reranker score (or fused rank score if reranking is off)


@dataclass(frozen=True)
class SearchResult:
    hits: list[SearchHit]
    blocked: int = 0  # results removed by the STEP 5 double-check (should always be 0)


# =============================================================================
# 2. THE SEARCH
# =============================================================================
def search(
    user: Principal,
    query: str,
    *,
    embedder: Embedder,
    reranker: Reranker | None,
    top_k: int | None = None,
    client: QdrantClient | None = None,
    collection: str | None = None,
) -> SearchResult:
    settings = get_settings()
    client = client or get_qdrant_client()
    collection = collection or settings.qdrant_collection
    top_k = top_k or settings.search_top_k

    # --- STEP 1: validate ---
    query = query.strip()
    if not query or len(query) > MAX_QUERY_CHARS:
        raise ValueError(f"query must be 1-{MAX_QUERY_CHARS} characters")
    if not client.collection_exists(collection):
        raise SearchUnavailable("the search index has not been built yet")

    # --- STEP 2: who may read what ---
    acl = build_acl_filter(user)

    # --- STEP 3: question -> vectors ---
    vec = embedder.embed_query(query)

    # --- STEP 4: hybrid search; the SAME access filter on every path ---
    prefetch = [models.Prefetch(
        query=vec.dense, using=DENSE, filter=acl, limit=settings.search_candidates)]
    if vec.sparse.indices:  # a question with no known words has an empty keyword vector
        prefetch.append(models.Prefetch(
            query=models.SparseVector(indices=vec.sparse.indices, values=vec.sparse.values),
            using=SPARSE, filter=acl, limit=settings.search_candidates))
    points = client.query_points(
        collection,
        prefetch=prefetch,
        query=models.FusionQuery(fusion=models.Fusion.RRF),  # merge both ranked lists
        query_filter=acl,  # and once more on the fused result
        limit=settings.search_candidates,
        with_payload=True,
    ).points

    # --- STEP 5: defense in depth - re-check every result against the oracle ---
    violations = [p for p in points if not _payload_readable(user, p.payload)]
    if violations:
        security_log.critical(
            "SECURITY: access filter returned %d unreadable chunk(s) to user %s: %s - "
            "returning no results", len(violations), user.user_id,
            [str(p.id) for p in violations],
        )
        return SearchResult(hits=[], blocked=len(violations))  # fail closed

    # --- STEP 6: rerank and keep the best top_k ---
    hits = [_to_hit(p.payload, str(p.id), p.score) for p in points]
    if reranker is not None and hits:
        scores = reranker.rerank(query, [h.text for h in hits])
        hits = [replace(h, score=s) for h, s in zip(hits, scores, strict=True)]
        hits.sort(key=lambda h: h.score, reverse=True)

    logger.info("search user=%s results=%d", user.user_id, min(len(hits), top_k))
    return SearchResult(hits=hits[:top_k])


# =============================================================================
# 3. HELPERS
# =============================================================================
# Rebuild the ACL from what Qdrant returned and ask the oracle. A payload with missing
# or malformed ACL fields counts as NOT readable (fail closed).
def _payload_readable(user: Principal, payload: dict | None) -> bool:
    try:
        acl = ResourceACL(
            clearance_level=payload["clearance_level"],
            departments=payload["departments"],
            allowed_users=payload["allowed_users"],
            denied_users=payload["denied_users"],
        )
    except (KeyError, TypeError, ValidationError):
        return False
    return can_read(user, acl)


def _to_hit(payload: dict, point_id: str, score: float) -> SearchHit:
    return SearchHit(
        chunk_id=point_id,
        doc_id=payload["doc_id"],
        doc_title=payload["doc_title"],
        section=payload.get("section"),
        page=payload.get("page"),
        sheet=payload.get("sheet"),
        classification=payload["classification"],
        text=payload["text"],
        score=float(score),
    )
