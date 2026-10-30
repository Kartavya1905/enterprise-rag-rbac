"""
FILE:         tests/unit/test_health.py
WHAT IT TESTS: The /health and /health/ready endpoints (app/api/health.py).
WHERE IT FITS: Phase 1.
"""

from fastapi.testclient import TestClient

from app.api import health


# TEST 1: liveness always answers "ok" while the app is running.
def test_liveness(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# TEST 2: with both in-memory databases up, readiness reports "ready" (HTTP 200).
def test_readiness_all_components_up(client: TestClient) -> None:
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["components"]["database"]["ok"] is True
    assert body["components"]["vectorstore"]["ok"] is True


# TEST 3: simulate Qdrant being down -> readiness must say "degraded" with HTTP 503.
def test_readiness_reports_degraded_when_a_component_fails(client: TestClient, monkeypatch) -> None:
    # Replace the real Qdrant check with one that always fails.
    monkeypatch.setattr(
        health,
        "check_vectorstore",
        lambda: health.ComponentStatus(ok=False, detail="ConnectionError"),
    )
    resp = client.get("/health/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["components"]["vectorstore"] == {"ok": False, "detail": "ConnectionError"}
