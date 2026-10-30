"""
FILE:         app/generation/answer.py
WHAT IT DOES: THE ANSWER PIPELINE. A verified user's question in, a grounded, cited,
              checked answer out.
WHERE IT FITS: Phase 7 - ties together search (Phase 6), the security guards and the LLM.
USED BY:      api/query.py, tests.

    STEP 1  INPUT GUARD     question looks like a prompt injection?  -> refuse
    STEP 2  SECURE SEARCH   top chunks THIS user may read             (Phase 6)
    STEP 3  CONTEXT GUARD   drop chunks that contain injections;
                            redact tax IDs / bank accounts in what's left
    STEP 4  nothing left?   -> neutral "couldn't find" answer, NO LLM call
    STEP 5  LLM             fixed rules + fenced sources + question
    STEP 6  OUTPUT GUARD    canary leak? redact, validate citations, grounding
    STEP 7  attach the cited sources (title, section, page) for the user
"""

import logging
import time
from dataclasses import dataclass, field

from app.core.access import Principal
from app.generation.llm import LLM
from app.generation.prompts import NO_ANSWER, SYSTEM_PROMPT, PromptSource, build_user_message
from app.retrieval.embeddings import Embedder
from app.retrieval.reranker import Reranker
from app.retrieval.search import SearchHit, search
from app.security.injection import detect_injection
from app.security.output_guard import check_answer
from app.security.redaction import redact

logger = logging.getLogger(__name__)
security_log = logging.getLogger("security")

REFUSAL = (
    "I can't help with that request. Please ask a question about company documents."
)


# =============================================================================
# 1. RESULT SHAPES
# =============================================================================
@dataclass(frozen=True)
class SourceRef:
    source_id: str  # "S1" - matches the [S1] markers in the answer
    doc_title: str
    location: str  # section / sheet / page


@dataclass
class Answer:
    text: str
    citations: list[SourceRef]  # sources the answer actually cites
    sources: list[SourceRef]  # everything the model was shown
    flags: list[str] = field(default_factory=list)  # internal: logged, not shown
    refused: bool = False
    # --- for the audit log (Phase 9); never returned to the caller ---
    retrieved_doc_ids: list[str] = field(default_factory=list)  # what search returned
    cited_doc_ids: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)  # milliseconds per step
    # --- for evaluations (Phase 11); never returned or logged ---
    context_texts: list[str] = field(default_factory=list)  # exactly what the LLM was shown

    @property
    def outcome(self) -> str:
        if self.refused:
            return "refused"  # injection in the question
        if "canary_leak" in self.flags:
            return "blocked"  # output guard replaced the answer
        if not self.sources:
            return "no_results"  # nothing readable matched
        return "ok"


# =============================================================================
# 2. THE PIPELINE
# =============================================================================
def answer_question(
    user: Principal, question: str, *, embedder: Embedder, reranker: Reranker | None, llm: LLM
) -> Answer:
    # --- STEP 1: input guard ---
    verdict = detect_injection(question)
    if verdict.flagged:
        security_log.warning("Blocked question from %s: %s", user.user_id, verdict.reasons)
        return Answer(REFUSAL, [], [], [f"input_injection:{r}" for r in verdict.reasons],
                      refused=True)

    # --- STEP 2: secure search (filtered by this user's access, double-checked) ---
    started = time.perf_counter()
    result = search(user, question, embedder=embedder, reranker=reranker)
    hits = result.hits
    timings = {"search_ms": (time.perf_counter() - started) * 1000}
    retrieved = [h.doc_id for h in hits]

    # --- STEP 3: context guard ---
    flags: list[str] = ["acl_double_check_blocked"] if result.blocked else []
    sources: list[PromptSource] = []
    source_docs: list[str] = []  # doc_id behind each source, for the audit log
    for hit in hits:
        poisoned = detect_injection(hit.text)
        if poisoned.flagged:
            security_log.warning("Dropped poisoned chunk %s (%s) for %s: %s", hit.chunk_id,
                                 hit.doc_id, user.user_id, poisoned.reasons)
            flags.append(f"context_injection:{hit.doc_id}")
            continue
        clean = redact(hit.text)
        flags += [f"context_redacted:{kind}" for kind in clean.redacted]
        sources.append(PromptSource(f"S{len(sources) + 1}", hit.doc_title, _location(hit),
                                    clean.text))
        source_docs.append(hit.doc_id)

    # --- STEP 4: nothing usable -> same neutral answer for everyone, no LLM call ---
    if not sources:
        return Answer(NO_ANSWER, [], [], flags, retrieved_doc_ids=retrieved, timings=timings)

    # --- STEP 5: ask the model ---
    started = time.perf_counter()
    raw = llm.generate(SYSTEM_PROMPT, build_user_message(question, sources))
    timings["llm_ms"] = (time.perf_counter() - started) * 1000

    # --- STEP 6: output guard ---
    guarded = check_answer(raw, {s.source_id for s in sources})
    flags += guarded.flags
    if guarded.blocked:
        security_log.critical("Blocked answer for %s: %s", user.user_id, guarded.flags)

    # --- STEP 7: citations the user can follow ---
    refs = {s.source_id: SourceRef(s.source_id, s.title, s.location) for s in sources}
    doc_of = {s.source_id: hit_doc for s, hit_doc in zip(sources, source_docs, strict=True)}
    answer = Answer(
        text=guarded.text,
        citations=[refs[i] for i in guarded.cited_ids],
        sources=list(refs.values()),
        flags=flags,
        retrieved_doc_ids=retrieved,
        cited_doc_ids=[doc_of[i] for i in guarded.cited_ids],
        timings=timings,
        context_texts=[s.text for s in sources],
    )
    logger.info("answer user=%s sources=%d cited=%d flags=%s", user.user_id,
                len(sources), len(answer.citations), flags)
    return answer


def _location(hit: SearchHit) -> str:
    parts = [hit.section or hit.sheet or ""]
    if hit.page:
        parts.append(f"page {hit.page}")
    return ", ".join(p for p in parts if p)
