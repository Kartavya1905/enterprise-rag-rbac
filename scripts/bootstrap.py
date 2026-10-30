"""
FILE:         scripts/bootstrap.py
WHAT IT DOES: One command from "empty databases" to "ready to answer questions":
                1. check the documents + manifest are there
                2. create the persona login accounts       (scripts/seed_users.py, not prod)
                3. parse + chunk + register the documents  (scripts/ingest_documents.py)
                4. embed + index the chunks into Qdrant     (scripts/index_chunks.py)
                5. check the local LLM has its model pulled
WHERE IT FITS: Phase 12. Each step is the existing script, run in order. Re-running is
              safe: users are updated in place and unchanged documents are skipped.
RUN:
    docker compose exec api python -m scripts.bootstrap    # inside Docker (recommended)
    python -m scripts.bootstrap                            # local dev: SQLite + embedded Qdrant
    python -m scripts.bootstrap --docker                   # from this PC into Docker's databases
"""

import argparse
import os
import subprocess
import sys

import httpx

from app.core.config import get_settings

# The dev stack's addresses as seen from this computer (ports published on 127.0.0.1).
DOCKER_DATABASE_URL = "postgresql+psycopg://rag:rag_dev_password@localhost:5432/enterprise_rag"
DOCKER_QDRANT_URL = "http://localhost:6333"


# =============================================================================
# 1. HELPERS
# =============================================================================
def _step(number: int, title: str) -> None:
    print(f"\n=== {number}/5 {title} " + "=" * max(0, 60 - len(title)), flush=True)


def _run(module: str, *args: str) -> None:
    """Run one of the existing scripts as its own process; stop everything if it fails."""
    result = subprocess.run([sys.executable, "-m", module, *args], check=False)
    if result.returncode != 0:
        raise SystemExit(f"\nBootstrap stopped: {module} failed (exit {result.returncode}).")


def _check_llm() -> None:
    """Warn (don't fail) when Ollama is down or the model isn't pulled: search still works."""
    settings = get_settings()
    try:
        tags = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=5).json()
    except (httpx.HTTPError, ValueError) as exc:
        print(f"WARNING: Ollama not reachable at {settings.ollama_base_url} "
              f"({type(exc).__name__}). /search works; /query will answer 503 until it runs:\n"
              "  docker compose --profile llm up -d ollama")
        return
    names = {m.get("name") for m in tags.get("models", [])}
    if settings.llm_model in names:
        print(f"OK: Ollama has {settings.llm_model}")
    else:
        print(f"WARNING: Ollama is running but {settings.llm_model} is not pulled:\n"
              f"  docker compose exec ollama ollama pull {settings.llm_model}")


# =============================================================================
# 2. THE STEPS
# =============================================================================
def main() -> None:
    parser = argparse.ArgumentParser(description="Seed users, ingest and index in one go.")
    parser.add_argument("--docker", action="store_true",
                        help="from the host, target the Docker Postgres + Qdrant (dev stack)")
    parser.add_argument("--database-url", help="override DATABASE_URL")
    parser.add_argument("--qdrant-url", help="override QDRANT_URL")
    parser.add_argument("--skip-llm-check", action="store_true",
                        help="don't check Ollama (CI has no LLM)")
    args = parser.parse_args()

    database_url = args.database_url or (DOCKER_DATABASE_URL if args.docker else None)
    qdrant_url = args.qdrant_url or (DOCKER_QDRANT_URL if args.docker else None)
    # Set for this process (the LLM check) and inherited by every step's process.
    if database_url:
        os.environ["DATABASE_URL"] = database_url
    if qdrant_url:
        os.environ["QDRANT_URL"] = qdrant_url
    get_settings.cache_clear()
    settings = get_settings()

    # --- STEP 1: documents present? (generated on a dev machine, committed to the repo) ---
    _step(1, "Documents")
    manifest = os.path.join(settings.documents_dir, "manifest.yaml")
    if not os.path.isfile(manifest):
        raise SystemExit(f"No manifest at {manifest}. Generate the dataset first "
                         "(dev machine): python -m scripts.generate_dataset")
    print(f"OK: {manifest}")

    _step(2, "Login accounts")
    if settings.environment == "prod":
        # Demo personas are refused in prod (scripts/seed_users.py); real people are added
        # one by one instead.
        print("ENVIRONMENT=prod: demo personas skipped. Add real accounts with:\n"
              "  docker compose exec api python -m scripts.create_user --help")
    else:
        _run("scripts.seed_users")

    _step(3, "Ingest documents")
    _run("scripts.ingest_documents")

    _step(4, "Index into Qdrant (first run downloads ~150 MB of models)")
    _run("scripts.index_chunks")

    _step(5, "Local LLM")
    if args.skip_llm_check:
        print("skipped")
    else:
        _check_llm()

    print("\nReady. Open http://localhost:8000/app/")
    if settings.environment != "prod":
        print("Persona passwords are in data/org/dev_credentials.yaml")


if __name__ == "__main__":
    main()
