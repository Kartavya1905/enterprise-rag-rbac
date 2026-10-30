"""
FILE:         tests/unit/test_rate_limit.py
WHAT IT TESTS: Rate limiting (app/core/rate_limit.py) and the security headers added to
              every response (app/main.py).
WHERE IT FITS: Phase 8.
"""

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.rate_limit import RateLimiter


# =============================================================================
# THE LIMITER ITSELF
# =============================================================================
def test_limiter_allows_up_to_the_limit_then_refuses() -> None:
    limiter = RateLimiter()
    assert all(limiter.hit("k", limit=3) is None for _ in range(3))
    retry_after = limiter.hit("k", limit=3)
    assert retry_after is not None and 0 < retry_after <= 60
    assert limiter.hit("other-key", limit=3) is None  # keys are independent


def test_old_requests_leave_the_window() -> None:
    limiter = RateLimiter()
    assert limiter.hit("k", limit=1, window=0.0) is None
    assert limiter.hit("k", limit=1, window=0.0) is None  # previous hit already expired


# =============================================================================
# ON THE API
# =============================================================================
def test_login_is_limited_per_ip(client: TestClient, seeded, monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_LOGIN", "3")
    get_settings.cache_clear()
    form = {"username": "nobody@orbitra.example", "password": "guess"}
    codes = [client.post("/auth/login", data=form).status_code for _ in range(4)]
    assert codes == [401, 401, 401, 429]
    blocked = client.post("/auth/login", data=form)
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) >= 1
    # Even the RIGHT password is refused while the IP is over its limit.
    creds = seeded["u_ceo"]
    right = client.post("/auth/login",
                        data={"username": creds["email"], "password": creds["password"]})
    assert right.status_code == 429


def test_search_is_limited_per_user_not_globally(client: TestClient, login, ingested,
                                                 monkeypatch) -> None:
    from app.retrieval.embeddings import get_embedder
    from app.retrieval.indexer import index_chunks
    from app.retrieval.reranker import get_reranker
    from tests.fakes import HashingEmbedder, OverlapReranker

    emb = HashingEmbedder()
    index_chunks(ingested.chunks, embedder=emb)
    client.app.dependency_overrides[get_embedder] = lambda: emb
    client.app.dependency_overrides[get_reranker] = lambda: OverlapReranker()
    intern, ceo = login("u_intern"), login("u_ceo")

    monkeypatch.setenv("RATE_LIMIT_SEARCH", "2")
    get_settings.cache_clear()
    try:
        body = {"query": "paid time off"}
        assert [client.post("/search", json=body, headers=intern).status_code
                for _ in range(3)] == [200, 200, 429]
        # A different user is unaffected by the intern hitting their limit.
        assert client.post("/search", json=body, headers=ceo).status_code == 200
    finally:
        client.app.dependency_overrides.clear()


# =============================================================================
# SECURITY HEADERS
# =============================================================================
def test_security_headers_on_every_response(client: TestClient) -> None:
    for path in ("/health", "/auth/me"):  # a 200 and a 401
        headers = client.get(path).headers
        assert headers["cache-control"] == "no-store"  # confidential answers never cached
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY"
