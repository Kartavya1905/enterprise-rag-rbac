"""
FILE:         tests/conftest.py
WHAT IT DOES: Shared test setup ("fixtures"). pytest loads this file automatically and any
              test can ask for a fixture just by naming it as a parameter.
WHERE IT FITS: Phase 1 (+ Phase 3 additions). Gives every test an isolated app wired to
              in-memory SQLite and in-memory Qdrant, so tests never touch your real data.
USED BY:      every file under tests/.

Fixtures:
    test_env  -> points settings at throwaway in-memory databases + test secrets
    client    -> a fake HTTP client that calls the API without starting a server
    seeded    -> `client` plus the 8 persona accounts created   (Phase 3)
    login     -> helper: log in as a persona, get back the auth headers   (Phase 3)
    dataset   -> a freshly generated copy of the 18 documents (once per run) (Phase 2)
    personas  -> the 8 demo personas                                       (Phase 2)
    ingested  -> the dataset run through the ingestion pipeline           (Phase 4)
"""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.database import get_engine, get_session_factory
from app.core.vectorstore import get_qdrant_client

TEST_JWT_SECRET = "test-only-signing-secret-" + "x" * 40


# The app caches settings and connections (@lru_cache). Clearing them forces the next call
# to re-read the environment variables the test just set.
def _clear_caches() -> None:
    for cached in (get_settings, get_engine, get_session_factory, get_qdrant_client):
        cached.cache_clear()


# =============================================================================
# FIXTURE 1: test_env - in-memory databases for the duration of one test
# =============================================================================
@pytest.fixture
def test_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # monkeypatch sets env vars for this test only and restores them afterwards.
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("DATABASE_URL", "sqlite://")  # SQLite in RAM
    monkeypatch.setenv("QDRANT_PATH", ":memory:")  # Qdrant in RAM
    monkeypatch.delenv("QDRANT_URL", raising=False)  # never hit a real server
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)  # never your real .env secret
    monkeypatch.setenv("PASSWORD_HASH_ROUNDS", "4")  # fast bcrypt for tests
    monkeypatch.setenv("DEMO_LOGIN", "false")  # never inherit a developer's .env choice
    # Tests log in and search many times per second; rate-limit tests lower these.
    for scope in ("LOGIN", "SEARCH", "QUERY", "ADMIN"):
        monkeypatch.setenv(f"RATE_LIMIT_{scope}", "10000")
    from app.core.rate_limit import limiter

    limiter.reset()
    _clear_caches()
    yield  # <- the test runs here
    limiter.reset()
    _clear_caches()


# =============================================================================
# FIXTURE 2: client - call the API like a browser would, without a real server
# =============================================================================
@pytest.fixture
def client(test_env: None) -> Iterator[TestClient]:
    from app.main import create_app

    # "with" runs the app's startup (creates tables) and shutdown around the test.
    with TestClient(create_app()) as test_client:
        yield test_client


# =============================================================================
# FIXTURE 3: seeded - the app with all 8 persona accounts created
# =============================================================================
# Returns {user_id: {"email": ..., "password": ...}}.
@pytest.fixture
def seeded(client: TestClient, tmp_path) -> dict[str, dict[str, str]]:
    from scripts.seed_users import seed

    with get_session_factory()() as db:
        return seed(db, tmp_path / "dev_credentials.yaml")


# =============================================================================
# FIXTURE 4: login - log in as a persona and get request headers with the token
# =============================================================================
@pytest.fixture
def login(client: TestClient, seeded) -> Callable[[str], dict[str, str]]:
    def _login(user_id: str) -> dict[str, str]:
        creds = seeded[user_id]
        resp = client.post(
            "/auth/login", data={"username": creds["email"], "password": creds["password"]}
        )
        assert resp.status_code == 200, resp.text
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    return _login


# =============================================================================
# FIXTURE 5: dataset - generate the 18 documents ONCE into a temp folder
# =============================================================================
# scope="session": built once for the whole test run, shared by every test file.
# Returns (raw_dir, manifest, golden_qa).
@pytest.fixture(scope="session")
def dataset(tmp_path_factory):
    from scripts.generate_dataset import generate

    data_dir = tmp_path_factory.mktemp("data")
    manifest, golden = generate(data_dir)
    return data_dir / "raw", manifest, golden


@pytest.fixture(scope="session")
def personas():
    from app.auth.personas import load_personas

    return load_personas()


# =============================================================================
# FIXTURE 6: ingested - the generated dataset run through the Phase 4 pipeline
# =============================================================================
# No database here (registry tests use `client`). Returns the IngestionReport.
@pytest.fixture(scope="session")
def ingested(dataset, tmp_path_factory):
    from app.ingestion.pipeline import ingest

    raw_dir: Path = dataset[0]
    return ingest(raw_dir / "manifest.yaml", out_dir=tmp_path_factory.mktemp("processed"))
