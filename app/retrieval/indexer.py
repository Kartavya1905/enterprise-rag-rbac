"""
FILE:         app/retrieval/indexer.py
WHAT IT DOES: Loads chunks into Qdrant: embeds their text and stores each one as a point
              whose payload carries the chunk's ACL. Incremental - only documents whose
              chunks changed are re-embedded.
WHERE IT FITS: Phase 5 - after ingestion (Phase 4), before search (Phase 6).
USED BY:      scripts/index_chunks.py, tests; Phase 8's upload API.

For each document:
    STEP 1  fingerprint its chunks (text + ACL + metadata)
    STEP 2  if Qdrant already holds exactly this fingerprint -> "unchanged", skip
    STEP 3  otherwise DELETE the document's old points, then embed + UPSERT the new ones
Then:
    STEP 4  delete points of documents that are no longer in the chunk set

Security choices:
    - The fingerprint includes the ACL, not just the file contents. Changing who may read
      a document (manifest edit, same file) MUST reach the index - otherwise the old,
      possibly looser label would keep being served.
    - Delete-then-insert: if indexing crashes midway, a document is briefly MISSING
      (safe) rather than present with an outdated label (unsafe).
    - An empty chunk set is refused: step 4 would otherwise wipe the whole index.
"""

import hashlib
import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass

from qdrant_client import QdrantClient, models

from app.core.config import get_settings
from app.core.vectorstore import get_qdrant_client
from app.ingestion.schemas import Chunk
from app.retrieval.collection import DENSE, SPARSE, ensure_collection
from app.retrieval.embeddings import Embedder, get_embedder

logger = logging.getLogger(__name__)

BATCH_SIZE = 32  # chunks embedded + uploaded per round trip


# =============================================================================
# 1. REPORT SHAPES
# =============================================================================
@dataclass
class DocIndexResult:
    doc_id: str
    status: str  # indexed | unchanged
    points: int


@dataclass
class IndexReport:
    documents: list[DocIndexResult]
    removed_docs: list[str]  # documents deleted from the index (no longer ingested)
    total_points: int  # points in the collection after this run


# =============================================================================
# 2. MAIN ENTRY
# =============================================================================
def index_chunks(
    chunks: list[Chunk],
    *,
    client: QdrantClient | None = None,
    embedder: Embedder | None = None,
    collection: str | None = None,
    recreate: bool = False,
) -> IndexReport:
    if not chunks:
        raise ValueError("refusing to index an empty chunk set (it would wipe the index)")
    client = client or get_qdrant_client()
    embedder = embedder or get_embedder()
    collection = collection or get_settings().qdrant_collection
    ensure_collection(client, collection, embedder.dense_dim, recreate=recreate)

    # Group chunks by document, keeping their order.
    by_doc: dict[str, list[Chunk]] = {}
    for chunk in chunks:
        by_doc.setdefault(chunk.doc_id, []).append(chunk)

    results = []
    for doc_id, doc_chunks in by_doc.items():
        # STEP 1 + 2
        fingerprint = document_fingerprint(doc_chunks)
        if _is_current(client, collection, doc_id, fingerprint, len(doc_chunks)):
            results.append(DocIndexResult(doc_id, "unchanged", len(doc_chunks)))
            continue
        # STEP 3: delete old version first (fail closed), then insert the new one
        client.delete(collection, points_selector=_doc_filter(doc_id), wait=True)
        for batch in _batches(doc_chunks, BATCH_SIZE):
            client.upsert(collection, points=_to_points(batch, embedder, fingerprint), wait=True)
        logger.info("Indexed %s (%d chunks)", doc_id, len(doc_chunks))
        results.append(DocIndexResult(doc_id, "indexed", len(doc_chunks)))

    # STEP 4
    removed = _remove_missing_docs(client, collection, set(by_doc))
    total = client.count(collection, exact=True).count
    return IndexReport(results, removed, total)


# =============================================================================
# 3. FINGERPRINT - changes when text, ACL or metadata of ANY chunk changes
# =============================================================================
def document_fingerprint(doc_chunks: list[Chunk]) -> str:
    # ingested_at changes every run without meaning anything changed - leave it out.
    payload = [c.model_dump(mode="json", exclude={"ingested_at"}) for c in doc_chunks]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


# "Already indexed" = every point of this doc has this fingerprint, and the count matches.
def _is_current(
    client: QdrantClient, collection: str, doc_id: str, fingerprint: str, expected: int
) -> bool:
    total = client.count(collection, count_filter=_doc_filter(doc_id).filter, exact=True)
    matching = client.count(
        collection,
        count_filter=models.Filter(must=[
            models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id)),
            models.FieldCondition(key="index_fingerprint",
                                  match=models.MatchValue(value=fingerprint)),
        ]),
        exact=True,
    )
    return total.count == matching.count == expected


# =============================================================================
# 4. BUILDING POINTS - vectors + payload (the payload is where the ACL lives)
# =============================================================================
def _to_points(
    chunks: list[Chunk], embedder: Embedder, fingerprint: str
) -> list[models.PointStruct]:
    vectors = embedder.embed_passages([c.text for c in chunks])
    return [
        models.PointStruct(
            id=chunk.chunk_id,
            vector={
                DENSE: vec.dense,
                SPARSE: models.SparseVector(indices=vec.sparse.indices, values=vec.sparse.values),
            },
            # Full chunk (text + clearance_level + departments + allowed/denied users ...)
            payload=chunk.model_dump(mode="json") | {"index_fingerprint": fingerprint},
        )
        for chunk, vec in zip(chunks, vectors, strict=True)
    ]


# =============================================================================
# 5. HELPERS
# =============================================================================
def _doc_filter(doc_id: str) -> models.FilterSelector:
    return models.FilterSelector(filter=models.Filter(must=[
        models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id)),
    ]))


def _batches(items: list[Chunk], size: int) -> Iterable[list[Chunk]]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


# STEP 4: find and delete points whose document is not in the current chunk set.
def _remove_missing_docs(client: QdrantClient, collection: str, keep: set[str]) -> list[str]:
    stale = models.Filter(must_not=[
        models.FieldCondition(key="doc_id", match=models.MatchAny(any=sorted(keep))),
    ])
    removed: set[str] = set()
    offset = None
    while True:  # page through matching points to report which documents go
        points, offset = client.scroll(
            collection, scroll_filter=stale, with_payload=["doc_id"], limit=256, offset=offset
        )
        removed |= {p.payload["doc_id"] for p in points}
        if offset is None:
            break
    if removed:
        client.delete(collection, points_selector=models.FilterSelector(filter=stale), wait=True)
        logger.info("Removed documents from index: %s", sorted(removed))
    return sorted(removed)
