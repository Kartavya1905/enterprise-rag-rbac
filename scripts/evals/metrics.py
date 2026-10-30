"""
FILE:         scripts/evals/metrics.py
WHAT IT DOES: Small, standard scoring functions used by the evaluations.
WHERE IT FITS: Phase 11. Unit-tested in tests/evals/test_metrics.py.

    recall_at_k   was the right document among the top k results?   (1 or 0)
    reciprocal_rank  1 / position of the right document              (1, 0.5, 0.33 ... or 0)
                  -> averaged over all questions this is MRR ("mean reciprocal rank")
    numbers_grounded  does every number in an answer appear in its sources?
"""

import re

from scripts.evals.corpus import normalize


def recall_at_k(ranked_doc_ids: list[str], expected: str, k: int) -> float:
    return 1.0 if expected in ranked_doc_ids[:k] else 0.0


def reciprocal_rank(ranked_doc_ids: list[str], expected: str, k: int = 10) -> float:
    for position, doc_id in enumerate(ranked_doc_ids[:k], start=1):
        if doc_id == expected:
            return 1.0 / position
    return 0.0


def mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


def unique_in_order(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


# Numbers like 310,000 / $1.38M / 18% / 4 - ignoring the [S1] citation markers.
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def numbers_grounded(answer: str, context_texts: list[str]) -> bool:
    """True if every number in the answer also appears in the sources the model saw.
    A number the model invented (a "hallucination") makes this False."""
    answer = re.sub(r"\[S\d+\]", "", answer)
    context = normalize(" ".join(context_texts))
    return all(normalize(n) in context for n in _NUMBER.findall(answer))
