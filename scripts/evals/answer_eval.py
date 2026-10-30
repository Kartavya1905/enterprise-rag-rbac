"""
FILE:         scripts/evals/answer_eval.py
WHAT IT DOES: Measures the QUALITY of LLM answers on the 21 golden questions:
                AUTHORIZED asker (lowest clearance that may know the answer)
                  correct     the known fact is in the answer
                  cited       the right document is among the citations
                  grounded    every number in the answer appears in its sources
                              (an invented number = a hallucination)
                UNAUTHORIZED asker (highest-clearance persona that may NOT know it)
                  leaked      the known fact appears anyway  (target: 0)
                  refused     answered with the neutral "couldn't find" sentence
WHERE IT FITS: Phase 11.
USED BY:      scripts/run_evals.py.
"""

import re
import time

from app.auth.personas import Persona
from app.generation.answer import answer_question
from app.generation.llm import LLM
from app.generation.prompts import NO_ANSWER
from app.ingestion.schemas import Chunk
from app.retrieval.embeddings import Embedder
from app.retrieval.reranker import Reranker
from scripts.evals.corpus import Question, can_answer, normalize
from scripts.evals.metrics import mean, numbers_grounded


def is_correct(q: Question, answer: str) -> bool:
    """Lenient on wording, strict on facts: the answer key's fact is there verbatim, or
    every number in it is, or every evidence string from the document is."""
    text = normalize(answer)
    numbers = re.findall(r"\d+(?:\.\d+)?", normalize(q.answer or ""))
    return (normalize(q.answer or "") in text
            or (bool(numbers) and all(n in text for n in numbers))
            or all(normalize(e) in text for e in q.evidence))


def answer_eval(golden: list[Question], personas: dict[str, Persona], chunks: list[Chunk],
                emb: Embedder, rr: Reranker, llm: LLM) -> dict:
    rows, correct, cited, grounded, latency = [], [], [], [], []
    leaks = refusals = unauthorized_asked = 0
    ranked = sorted(personas.values(), key=lambda p: (p.clearance, p.user_id))

    for q in golden:
        # --- AUTHORIZED: the lowest-clearance persona that can know the answer ---
        asker = next(p for p in ranked if can_answer(p, q, chunks))
        started = time.perf_counter()
        result = answer_question(asker, q.question, embedder=emb, reranker=rr, llm=llm)
        latency.append(time.perf_counter() - started)
        ok = is_correct(q, result.text)
        correct.append(float(ok))
        cited.append(float(q.doc_id in result.cited_doc_ids))
        grounded.append(float(numbers_grounded(result.text, result.context_texts)))
        row = {"id": q.question, "asked_by": asker.user_id, "correct": ok,
               "cited_right_doc": q.doc_id in result.cited_doc_ids,
               "numbers_grounded": grounded[-1] == 1.0, "answer": result.text[:200]}

        # --- UNAUTHORIZED: the most senior persona that still may NOT know it ---
        outsiders = [p for p in ranked if not can_answer(p, q, chunks)]
        if outsiders:
            outsider = outsiders[-1]
            denied = answer_question(outsider, q.question, embedder=emb, reranker=rr, llm=llm)
            unauthorized_asked += 1
            leak = is_correct(q, denied.text) and q.answer is not None
            leaks += leak
            refusals += denied.text == NO_ANSWER
            row |= {"denied_to": outsider.user_id, "leaked": leak,
                    "denied_answer": denied.text[:120]}
        rows.append(row)

    return {
        "questions": len(golden),
        "authorized": {"correct": mean(correct), "cited_right_doc": mean(cited),
                       "numbers_grounded": mean(grounded),
                       "avg_seconds": round(sum(latency) / len(latency), 2)},
        "unauthorized": {"asked": unauthorized_asked, "leaks": leaks,
                         "clean_refusals": refusals},
        "rows": rows,
    }
