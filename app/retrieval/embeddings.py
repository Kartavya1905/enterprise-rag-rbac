"""
FILE:         app/retrieval/embeddings.py
WHAT IT DOES: Turns text into vectors (lists of numbers) that a vector database can
              compare. Two kinds per text:
                DENSE   384 numbers capturing MEANING  - "vacation days" matches
                        "paid time off" even with no shared words      (BGE-small)
                SPARSE  a few weighted word ids - exact KEYWORD matching, great for
                        codes, names and numbers like "HR-2026-014"     (BM25)
              Using both = "hybrid search" (combined in Phase 6).
WHERE IT FITS: Phase 5 embeds every chunk for indexing; Phase 6 embeds each question.
USED BY:      retrieval/indexer.py, and (Phase 6) the search code.

Everything runs locally on CPU via FastEmbed (ONNX models, ~65 MB, downloaded once into
data/models/). No GPU, no API key, no cost.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from app.core.config import get_settings


# =============================================================================
# 1. VECTOR SHAPES
# =============================================================================
@dataclass(frozen=True)
class SparseVector:
    indices: list[int]  # which words (as ids) appear
    values: list[float]  # how much each one counts


@dataclass(frozen=True)
class EmbeddedText:
    dense: list[float]
    sparse: SparseVector


# =============================================================================
# 2. THE INTERFACE - anything that can embed text
# =============================================================================
# The indexer only depends on this interface, so tests can plug in a tiny offline fake
# and a future model swap touches only this file.
class Embedder(Protocol):
    @property
    def dense_dim(self) -> int: ...

    # Chunks being stored.
    def embed_passages(self, texts: Sequence[str]) -> list[EmbeddedText]: ...

    # A user's question. Embedded slightly differently: BGE adds a "query" instruction,
    # and BM25 doesn't count repeated words in a question.
    def embed_query(self, text: str) -> EmbeddedText: ...


# =============================================================================
# 3. THE REAL EMBEDDER - FastEmbed (local ONNX models)
# =============================================================================
class FastEmbedEmbedder:
    def __init__(self, dense_model: str, sparse_model: str, cache_dir: str) -> None:
        # Imported here so the app can start (e.g. /health) without loading models.
        from fastembed import SparseTextEmbedding, TextEmbedding

        self._dense = TextEmbedding(dense_model, cache_dir=cache_dir)
        self._sparse = SparseTextEmbedding(sparse_model, cache_dir=cache_dir)
        self.dense_model_name = dense_model

    @property
    def dense_dim(self) -> int:
        return self._dense.embedding_size

    def embed_passages(self, texts: Sequence[str]) -> list[EmbeddedText]:
        dense = self._dense.passage_embed(list(texts))
        sparse = self._sparse.embed(list(texts))
        return [_pack(d, s) for d, s in zip(dense, sparse, strict=True)]

    def embed_query(self, text: str) -> EmbeddedText:
        dense = next(iter(self._dense.query_embed([text])))
        sparse = next(iter(self._sparse.query_embed([text])))
        return _pack(dense, sparse)


def _pack(dense, sparse) -> EmbeddedText:
    # FastEmbed returns numpy arrays; Qdrant wants plain Python lists.
    return EmbeddedText(
        dense=[float(x) for x in dense],
        sparse=SparseVector(
            indices=[int(i) for i in sparse.indices],
            values=[float(v) for v in sparse.values],
        ),
    )


# =============================================================================
# 4. ACCESS POINT - one shared embedder per process (loading models takes seconds)
# =============================================================================
@lru_cache
def get_embedder() -> Embedder:
    s = get_settings()
    return FastEmbedEmbedder(s.embedding_model, s.sparse_model, s.model_cache_dir)
