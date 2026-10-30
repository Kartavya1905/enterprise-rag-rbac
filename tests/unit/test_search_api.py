"""
FILE:         tests/unit/test_search_api.py
WHAT IT TESTS: POST /search over HTTP (app/api/search.py): login required, results
              depend on WHO is asking, nothing about other users' access is exposed, and
              "no results" looks the same for everyone.
WHERE IT FITS: Phase 6. Uses the offline fakes in place of the real models.
"""

import pytest
from fastapi.testclient import TestClient

from app.api.search import NO_RESULTS_MESSAGE
from app.retrieval.embeddings import get_embedder
from app.retrieval.indexer import index_chunks
from app.retrieval.reranker import get_reranker
from tests.fakes import HashingEmbedder, OverlapReranker


@pytest.fixture
def api(client: TestClient, ingested, login):
    emb = HashingEmbedder()
    index_chunks(ingested.chunks, embedder=emb)
    # Swap the real models for the fakes inside the running app.
    client.app.dependency_overrides[get_embedder] = lambda: emb
    client.app.dependency_overrides[get_reranker] = lambda: OverlapReranker()
    yield client, login
    client.app.dependency_overrides.clear()


def _search(client, headers, query, **extra):
    return client.post("/search", json={"query": query, **extra}, headers=headers)


def test_search_requires_login(api) -> None:
    client, _ = api
    assert _search(client, {}, "anything").status_code == 401


# Same question, different people, different answers.
def test_results_depend_on_who_asks(api) -> None:
    client, login = api
    q = "Executive compensation CEO base salary"
    ceo = _search(client, login("u_ceo"), q).json()["results"]
    intern = _search(client, login("u_intern"), q).json()["results"]
    assert any(r["doc_title"] == "Executive Compensation 2026" for r in ceo)
    assert all(r["classification"] == "public" for r in intern)


# Sending role/clearance in the body changes nothing (and isn't even a field).
def test_body_cannot_raise_access(api) -> None:
    client, login = api
    resp = _search(client, login("u_intern"), "Executive compensation CEO base salary",
                   role="executive", clearance=4, user_id="u_ceo")
    assert resp.status_code == 200
    assert all(r["classification"] == "public" for r in resp.json()["results"])


# Results never reveal who else may or may not read a document.
def test_response_hides_acl_user_lists(api) -> None:
    client, login = api
    body = _search(client, login("u_eng_manager"), "cloud budget savings").json()
    for r in body["results"]:
        assert set(r) == {"doc_title", "section", "page", "sheet", "classification",
                          "text", "score"}


def test_input_limits(api) -> None:
    client, login = api
    headers = login("u_engineer")
    assert _search(client, headers, "").status_code == 422
    assert _search(client, headers, "x" * 1001).status_code == 422
    assert _search(client, headers, "ok", top_k=50).status_code == 422


# Before anything is indexed the API says "unavailable", not "no access".
def test_unindexed_search_is_unavailable(client: TestClient, login) -> None:
    client.app.dependency_overrides[get_embedder] = lambda: HashingEmbedder()
    client.app.dependency_overrides[get_reranker] = lambda: OverlapReranker()
    try:
        assert _search(client, login("u_ceo"), "anything").status_code == 503
    finally:
        client.app.dependency_overrides.clear()


def test_no_results_message_is_neutral() -> None:
    # The one message every user gets when nothing readable matches.
    assert "restricted" not in NO_RESULTS_MESSAGE.lower()
    assert "access to" in NO_RESULTS_MESSAGE
