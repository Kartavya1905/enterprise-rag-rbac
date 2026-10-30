"""
FILE:         tests/unit/test_search.py
WHAT IT TESTS: The secure search (app/retrieval/search.py): every result is readable,
              targeted "leak attempts" return nothing restricted, and the double-check
              fails CLOSED if the filter ever breaks.
WHERE IT FITS: Phase 6.

Sections:
    EVERY RESULT READABLE   all personas x all golden questions
    LEAK ATTEMPTS           pointed questions about things a persona must not see
    FAIL CLOSED             broken filter / corrupted payload -> nothing returned + alert
    VALIDATION              empty or oversized questions, missing index
    REAL MODELS             golden-question recall with the actual models, per user
"""

import logging

import pytest
from qdrant_client import models

from app.core.access import can_read
from app.core.config import get_settings
from app.core.vectorstore import get_qdrant_client
from app.retrieval import search as search_module
from app.retrieval.indexer import index_chunks
from app.retrieval.search import SearchUnavailable, search
from tests.fakes import HashingEmbedder, OverlapReranker

EMB, RR = HashingEmbedder(), OverlapReranker()


@pytest.fixture
def indexed(test_env, ingested):
    index_chunks(ingested.chunks, embedder=EMB)
    return {c.chunk_id: c for c in ingested.chunks}


def _search(user, query, **kw):
    return search(user, query, embedder=EMB, reranker=RR, **kw)


# =============================================================================
# EVERY RESULT READABLE
# =============================================================================
def test_every_result_is_readable_by_the_asker(indexed, dataset, personas) -> None:
    _, _, golden = dataset
    for persona in personas.values():
        for q in golden:
            for hit in _search(persona, q.question, top_k=10).hits:
                assert can_read(persona, indexed[hit.chunk_id]), (persona.user_id, q.id)


# =============================================================================
# LEAK ATTEMPTS - pointed questions; restricted content must never come back
# =============================================================================
@pytest.mark.parametrize(
    ("user_id", "question", "forbidden_doc"),
    [
        ("u_intern", "What is the CEO Helena Voss base salary bonus equity?",
         "exec-compensation-2026"),
        ("u_intern", "payroll Q3 2026 gross pay tax ID bank account", "payroll-2026-q3"),
        ("u_engineer", "Is there a layoff plan restructuring Austin office positions?",
         "restructuring-plan-2027"),
        ("u_sales_rep", "Project Atlas acquisition Lumen Analytics", "board-minutes-2026-q3"),
        ("u_hr_partner", "investigation HR-2026-014 Rafael Castillo outcome",
         "workplace-investigation-2026-07"),  # explicit deny beats HR department
        ("u_finance_analyst", "Executive compensation CEO CFO base salary",
         "exec-compensation-2026"),
        ("u_cfo", "telemetry TimescaleDB fleet-api architecture",
         "platform-architecture"),  # top clearance, wrong department
    ],
)
def test_pointed_questions_never_return_forbidden_docs(
    indexed, personas, user_id, question, forbidden_doc
) -> None:
    hits = _search(personas[user_id], question, top_k=10).hits
    assert forbidden_doc not in {h.doc_id for h in hits}


# Column-level security end to end: salary text only reaches HR/Finance/executives.
def test_directory_salaries_never_reach_other_users(indexed, personas) -> None:
    for uid, persona in personas.items():
        hits = _search(persona, "Lena Okafor Base Salary (USD)", top_k=10).hits
        sees_salary = any("Base Salary (USD):" in h.text for h in hits)
        assert sees_salary == (uid in {"u_hr_partner", "u_finance_analyst", "u_cfo", "u_ceo"})


# The named grant works: the engineering manager CAN find the finance cloud review.
def test_need_to_know_grant_is_searchable(indexed, personas) -> None:
    hits = _search(personas["u_eng_manager"], "FY2027 cloud budget savings target").hits
    assert "cloud-cost-review-fy2027" in {h.doc_id for h in hits}


# =============================================================================
# FAIL CLOSED - when something is wrong, return NOTHING and raise an alert
# =============================================================================
def test_broken_filter_is_caught_by_the_double_check(indexed, personas, monkeypatch,
                                                     caplog) -> None:
    # Simulate a bug: the access filter lets everything through.
    monkeypatch.setattr(search_module, "build_acl_filter", lambda user: None)
    with caplog.at_level(logging.CRITICAL, logger="security"):
        result = _search(personas["u_intern"], "CEO base salary executive compensation")
    assert result.hits == []
    assert result.blocked > 0
    assert "SECURITY" in caplog.text


def test_point_with_missing_acl_is_treated_as_unreadable(indexed, personas) -> None:
    client, name = get_qdrant_client(), get_settings().qdrant_collection
    handbook = next(c for c in indexed.values() if c.doc_id == "employee-handbook")
    # Corrupt one point: remove its departments field.
    client.delete_payload(name, keys=["departments"],
                          points=models.PointIdsList(points=[handbook.chunk_id]))
    hits = _search(personas["u_ceo"], "paid time off vacation days", top_k=10).hits
    assert handbook.chunk_id not in {h.chunk_id for h in hits}


# =============================================================================
# VALIDATION
# =============================================================================
def test_bad_queries_are_rejected(indexed, personas) -> None:
    for bad in ["", "   ", "x" * 1001]:
        with pytest.raises(ValueError):
            _search(personas["u_ceo"], bad)


def test_search_before_indexing_is_unavailable(test_env, personas) -> None:
    with pytest.raises(SearchUnavailable):
        _search(personas["u_ceo"], "anything")


# =============================================================================
# REAL MODELS - retrieval quality WITH access control, using the actual models
# =============================================================================
@pytest.fixture(scope="session")
def real_models():
    from app.retrieval.embeddings import FastEmbedEmbedder
    from app.retrieval.reranker import FastEmbedReranker

    s = get_settings()
    try:
        return (FastEmbedEmbedder(s.embedding_model, s.sparse_model, s.model_cache_dir),
                FastEmbedReranker(s.reranker_model, s.model_cache_dir))
    except Exception as exc:  # noqa: BLE001 - offline and models not cached yet
        pytest.skip(f"models unavailable: {exc}")


@pytest.mark.slow  # 21 questions x 8 users with real models (~2-3 min). Run: pytest -m slow
def test_golden_questions_with_access_control(test_env, ingested, dataset, personas,
                                              real_models) -> None:
    embedder, reranker = real_models
    index_chunks(ingested.chunks, embedder=embedder)
    _, manifest, golden = dataset
    found = 0
    for q in golden:
        doc = manifest.get(q.doc_id)
        for persona in personas.values():
            ids = {h.doc_id for h in search(persona, q.question, embedder=embedder,
                                            reranker=reranker).hits}
            if can_read(persona, doc):
                found += q.doc_id in ids
            else:
                assert q.doc_id not in ids, (persona.user_id, q.id)  # never leaks
    authorized_pairs = sum(can_read(p, manifest.get(q.doc_id))
                           for q in golden for p in personas.values())
    # Authorized users find the right document in their top 5 nearly every time.
    assert found / authorized_pairs >= 0.95
