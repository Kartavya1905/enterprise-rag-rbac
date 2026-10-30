"""
FILE:         tests/rbac_leak/test_leak_suite.py
WHAT IT TESTS: The RBAC LEAK SUITE on every `pytest` run: all 45 attacks in
              data/eval/attacks.yaml, as all 9 personas, through search AND through the
              full answer pipeline (with a recording fake LLM).
WHERE IT FITS: Phase 11. Uses offline fakes, so it runs in seconds; the same attacks
              run against the real models in `python -m scripts.run_evals`.

A leak = a secret that exists ONLY in chunks the persona may not read showing up in:
    - their search results, or
    - the prompt sent to the LLM (if the model never sees it, it cannot say it).
"""

import pytest

from app.core.access import can_read
from app.generation.answer import answer_question
from app.retrieval.indexer import index_chunks
from app.retrieval.search import search
from scripts.evals.corpus import forbidden_secrets, leaked, load_attacks, load_secrets
from tests.fakes import HashingEmbedder, OverlapReranker, ScriptedLLM

EMB, RR = HashingEmbedder(), OverlapReranker()
ATTACKS, SECRETS = load_attacks(), load_secrets()


@pytest.fixture
def indexed(test_env, ingested):
    index_chunks(ingested.chunks, embedder=EMB)
    return ingested.chunks


# The suite itself must be meaningful: every secret really exists, and every persona
# below the CEO has something forbidden.
def test_suite_is_meaningful(ingested, personas) -> None:
    corpus = " ".join(c.text for c in ingested.chunks)
    assert all(s in corpus for s in SECRETS), [s for s in SECRETS if s not in corpus]
    assert len(ATTACKS) >= 40
    for uid, persona in personas.items():
        if uid != "u_ceo":
            assert forbidden_secrets(persona, ingested.chunks, SECRETS), uid


@pytest.mark.parametrize("user_id", ["u_intern", "u_engineer", "u_sales_rep",
                                     "u_eng_manager", "u_hr_partner", "u_finance_analyst",
                                     "u_it_admin", "u_cfo", "u_ceo"])
def test_no_leaks_for_persona(indexed, personas, user_id) -> None:
    persona = personas[user_id]
    by_id = {c.chunk_id: c for c in indexed}
    forbidden = forbidden_secrets(persona, indexed, SECRETS)
    llm = ScriptedLLM("I couldn't find that in the documents you have access to.")
    problems = []
    for attack in ATTACKS:
        # --- search level ---
        hits = search(persona, attack, embedder=EMB, reranker=RR, top_k=10).hits
        unreadable = [h.chunk_id for h in hits if not can_read(persona, by_id[h.chunk_id])]
        found = leaked(" ".join(h.text for h in hits), forbidden, asked=attack)
        # --- pipeline level: what the LLM would be shown ---
        calls_before = len(llm.calls)
        answer_question(persona, attack, embedder=EMB, reranker=RR, llm=llm)
        prompt = llm.calls[-1][1] if len(llm.calls) > calls_before else ""
        found |= leaked(prompt, forbidden, asked=attack)  # the question itself is echoed
        if unreadable or found:
            problems.append((attack, unreadable, sorted(found)))
    assert problems == [], f"{user_id} leaked: {problems[:3]}"
