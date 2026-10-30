"""
FILE:         tests/fakes.py
WHAT IT IS:   Lightweight stand-ins used by tests.

HashingEmbedder    - a tiny, offline, deterministic Embedder. Words are hashed into a small
                     vector, so texts sharing words get similar vectors. Not smart, but
                     fast and good enough to test indexing/search MECHANICS and access
                     control without loading models.
OverlapReranker    - scores a text by how many question words it contains.
ScriptedLLM        - returns a fixed reply and records every prompt it was sent, so tests
                     can check exactly what the "model" saw.
"""

import math
import re
import zlib
from collections import Counter
from collections.abc import Sequence

from app.retrieval.embeddings import EmbeddedText, SparseVector


class HashingEmbedder:
    dense_dim = 64

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", text.lower())

    def _embed(self, text: str) -> EmbeddedText:
        counts = Counter(zlib.crc32(t.encode()) for t in self._tokens(text))  # stable hash
        dense = [0.0] * self.dense_dim
        for h, n in counts.items():
            dense[h % self.dense_dim] += n
        norm = math.sqrt(sum(x * x for x in dense)) or 1.0
        sparse = sorted((h % (2**20), float(n)) for h, n in counts.items())
        merged: dict[int, float] = {}
        for i, v in sparse:
            merged[i] = merged.get(i, 0.0) + v
        return EmbeddedText(
            dense=[x / norm for x in dense],
            sparse=SparseVector(indices=list(merged), values=list(merged.values())),
        )

    def embed_passages(self, texts: Sequence[str]) -> list[EmbeddedText]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> EmbeddedText:
        return self._embed(text)


class OverlapReranker:
    def rerank(self, query: str, texts: Sequence[str]) -> list[float]:
        words = set(HashingEmbedder._tokens(query))
        return [float(len(words & set(HashingEmbedder._tokens(t)))) for t in texts]


class ScriptedLLM:
    def __init__(self, reply: str = "The answer is in the handbook [S1].") -> None:
        self.reply = reply
        self.calls: list[tuple[str, str]] = []  # (system, user) per call

    def generate(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.reply
