"""
FILE:         scripts/evals/retrieval_eval.py
WHAT IT DOES: Measures how well each search strategy finds the right document:
                dense          meaning vectors only               (Phase 5)
                sparse         BM25 keywords only                 (Phase 5)
                hybrid         both, fused with RRF               (Phase 6)
                hybrid+rerank  hybrid, then the cross-encoder     (Phase 6 - what we ship)
WHERE IT FITS: Phase 11. Every mode uses the SAME access filter, so this is quality
              measured under real access control.
USED BY:      scripts/run_evals.py.

Asked as the CEO (who may read everything) = hardest case: all 71 chunks compete.
"""

from qdrant_client import QdrantClient, models

from app.auth.personas import Persona
from app.retrieval.acl_filter import build_acl_filter
from app.retrieval.collection import DENSE, SPARSE
from app.retrieval.embeddings import Embedder
from app.retrieval.reranker import Reranker
from app.retrieval.search import search
from scripts.evals.corpus import Question
from scripts.evals.metrics import mean, recall_at_k, reciprocal_rank, unique_in_order

MODES = ["dense", "sparse", "hybrid", "hybrid+rerank"]


def _ranked_docs(mode: str, user: Persona, question: str, emb: Embedder, rr: Reranker,
                 client: QdrantClient, collection: str) -> list[str]:
    acl = build_acl_filter(user)
    if mode == "hybrid+rerank":  # the real production search
        hits = search(user, question, embedder=emb, reranker=rr, top_k=10, client=client,
                      collection=collection).hits
        return unique_in_order([h.doc_id for h in hits])

    vec = emb.embed_query(question)
    sparse = models.SparseVector(indices=vec.sparse.indices, values=vec.sparse.values)
    if mode == "dense":
        result = client.query_points(collection, query=vec.dense, using=DENSE,
                                     query_filter=acl, limit=20, with_payload=["doc_id"])
    elif mode == "sparse":
        result = client.query_points(collection, query=sparse, using=SPARSE,
                                     query_filter=acl, limit=20, with_payload=["doc_id"])
    else:
        result = client.query_points(
            collection,
            prefetch=[models.Prefetch(query=vec.dense, using=DENSE, filter=acl, limit=20),
                      models.Prefetch(query=sparse, using=SPARSE, filter=acl, limit=20)],
            query=models.FusionQuery(fusion=models.Fusion.RRF), query_filter=acl,
            limit=20, with_payload=["doc_id"])
    return unique_in_order([p.payload["doc_id"] for p in result.points])


def evaluate_retrieval(questions: list[Question], user: Persona, emb: Embedder, rr: Reranker,
                       client: QdrantClient, collection: str) -> dict:
    results: dict = {}
    for mode in MODES:
        r1, r5, rr_scores, misses = [], [], [], []
        for q in questions:
            ranked = _ranked_docs(mode, user, q.question, emb, rr, client, collection)
            r1.append(recall_at_k(ranked, q.doc_id, 1))
            r5.append(recall_at_k(ranked, q.doc_id, 5))
            rr_scores.append(reciprocal_rank(ranked, q.doc_id))
            if not r5[-1]:
                misses.append(q.question)
        results[mode] = {"recall@1": mean(r1), "recall@5": mean(r5), "mrr@10": mean(rr_scores),
                         "misses@5": misses}
    return {"asked_as": user.user_id, "questions": len(questions), "modes": results}
