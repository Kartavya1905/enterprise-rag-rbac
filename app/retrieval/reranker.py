"""
FILE:         app/retrieval/reranker.py
WHAT IT DOES: Re-scores search candidates by reading the question and each chunk TOGETHER
              (a "cross-encoder"). Slower than vector search, but much sharper - so it
              only runs on the ~20 candidates hybrid search already found.
WHERE IT FITS: Phase 6 - last step of search, after access filtering.
USED BY:      retrieval/search.py, api/search.py.

Runs locally on CPU via FastEmbed (Xenova/ms-marco-MiniLM-L-6-v2, ~80 MB, free).
Scores are relative (higher = more relevant); they are NOT a reliable "is this relevant
at all" cutoff, so search keeps the top results instead of thresholding.
"""

from collections.abc import Sequence
from functools import lru_cache
from typing import Protocol

from app.core.config import get_settings


class Reranker(Protocol):
    def rerank(self, query: str, texts: Sequence[str]) -> list[float]: ...


class FastEmbedReranker:
    def __init__(self, model: str, cache_dir: str) -> None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        self._encoder = TextCrossEncoder(model, cache_dir=cache_dir)

    def rerank(self, query: str, texts: Sequence[str]) -> list[float]:
        return [float(s) for s in self._encoder.rerank(query, list(texts))]


@lru_cache
def get_reranker() -> Reranker:
    s = get_settings()
    return FastEmbedReranker(s.reranker_model, s.model_cache_dir)
