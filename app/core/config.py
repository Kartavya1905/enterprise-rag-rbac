"""
FILE:         app/core/config.py
WHAT IT DOES: Holds every setting the app needs (database address, Qdrant address, login
              secret, LLM model ...) and reads their values from environment variables or
              the `.env` file.
WHERE IT FITS: Phase 1 - foundation. Nothing in the app hard-codes an address or a secret;
              it always asks this file.
USED BY:      database.py, vectorstore.py, main.py, and (later) auth and generation code.

Flow:  .env file / environment variables  ->  Settings class (validated)  ->  get_settings()
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# =============================================================================
# 1. PATHS - where the project and its data folder live on disk
# =============================================================================
# parents[2] walks up from app/core/config.py -> app/core -> app -> project root.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"

# The placeholder secret from .env.example. Refused in production (see step 3).
DEFAULT_JWT_SECRET = "change-me"
MIN_PROD_SECRET_LENGTH = 32


# =============================================================================
# 2. THE SETTINGS - one field per setting, with a safe default for local dev
# =============================================================================
# pydantic-settings fills each field from an environment variable of the same name
# (case-insensitive): e.g. DATABASE_URL in .env -> settings.database_url.
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",  # read .env from the project root
        env_file_encoding="utf-8",
        extra="ignore",  # unknown keys in .env are ignored instead of crashing
    )

    # --- General ---
    app_name: str = "Enterprise RAG (RBAC)"
    environment: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"

    # --- Relational DB: users, roles, document registry, audit log ---
    # Default = a SQLite file at data/dev.db (no install needed).
    # In Docker this is overridden with a Postgres URL.
    database_url: str = f"sqlite:///{(DATA_DIR / 'dev.db').as_posix()}"

    # --- Vector DB (Qdrant): document chunks + their access labels ---
    # If qdrant_url is empty, embedded Qdrant is used at qdrant_path
    # (":memory:" for an ephemeral in-process instance, handy in tests).
    qdrant_url: str | None = None
    qdrant_path: str = str(DATA_DIR / "qdrant")
    qdrant_api_key: SecretStr | None = None  # SecretStr = never printed in logs
    qdrant_collection: str = "enterprise_docs"

    # --- Embedding models (Phase 5): run locally on CPU via FastEmbed, free ---
    # Dense = meaning ("vacation" ~ "paid time off"); sparse = exact words (BM25).
    embedding_model: str = "BAAI/bge-small-en-v1.5"  # 384 numbers per text, ~65 MB
    sparse_model: str = "Qdrant/bm25"
    model_cache_dir: str = str(DATA_DIR / "models")  # downloaded once, reused offline

    # --- Search (Phase 6) ---
    # Cross-encoder that re-reads question + chunk together for a sharper ranking (~80 MB).
    reranker_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    search_candidates: int = Field(default=20, ge=1, le=100)  # fused hits sent to reranker
    search_top_k: int = Field(default=5, ge=1, le=20)  # results returned to the caller

    # --- Rate limits (Phase 8): requests allowed per 60 seconds ---
    rate_limit_login: int = Field(default=10, ge=1)  # per client IP (slows password guessing)
    rate_limit_search: int = Field(default=60, ge=1)  # per user
    rate_limit_query: int = Field(default=30, ge=1)  # per user (each one runs the LLM)
    rate_limit_admin: int = Field(default=30, ge=1)  # per user

    # --- Demo login (Phase 10): one-click persona switcher in the web UI ---
    # DEV ONLY. Lets anyone who can reach the API log in as any user WITHOUT a password,
    # so it is off by default and the app refuses to start with it on in prod.
    demo_login: bool = False

    # --- Document administration (Phase 8) ---
    documents_dir: str = str(DATA_DIR / "raw")  # holds manifest.yaml + the files
    processed_dir: str = str(DATA_DIR / "processed")  # chunks.jsonl + report
    max_upload_mb: int = Field(default=10, ge=1, le=100)

    # --- Auth (Phase 3): login tokens (JWT) and password hashing ---
    jwt_secret_key: SecretStr = SecretStr(DEFAULT_JWT_SECRET)  # signs every token
    jwt_algorithm: Literal["HS256"] = "HS256"  # pinned: tokens with any other alg are rejected
    jwt_expire_minutes: int = Field(default=60, ge=1, le=24 * 60)
    jwt_issuer: str = "enterprise-rag"  # "who made this token" - checked on every request
    jwt_audience: str = "enterprise-rag-api"  # "who is it for" - checked on every request
    # bcrypt work factor: each +1 doubles the time to hash (and to brute-force) a password.
    # 12 is a sensible default; tests lower it to 4 so they run fast.
    password_hash_rounds: int = Field(default=12, ge=4, le=16)

    # --- LLM (Phase 7): local Ollama server (free, no API key) ---
    ollama_base_url: str = "http://localhost:11434"
    # qwen2.5:7b (~4.7 GB) reads tables and cites reliably; fits an 8 GB GPU.
    # On a CPU-only machine, llama3.2:3b (~2 GB) is faster but weaker with numbers.
    llm_model: str = "qwen2.5:7b"
    llm_temperature: float = Field(default=0.1, ge=0, le=1)  # low = factual, repeatable
    llm_max_tokens: int = Field(default=400, ge=50, le=2000)  # longest answer allowed
    llm_context_tokens: int = Field(default=4096, ge=1024)  # prompt + answer budget
    llm_timeout_seconds: float = Field(default=120, gt=0)

    # =========================================================================
    # 3. SAFETY CHECK - refuse to start production with a weak or placeholder secret
    # =========================================================================
    # Runs automatically after all fields are loaded. Anyone who knows (or guesses) the
    # secret could forge login tokens for any user, so prod needs a long random one.
    @model_validator(mode="after")
    def _check_prod_secrets(self) -> "Settings":
        if self.environment == "prod":
            secret = self.jwt_secret_key.get_secret_value()
            if secret == DEFAULT_JWT_SECRET or len(secret) < MIN_PROD_SECRET_LENGTH:
                raise ValueError(
                    f"JWT_SECRET_KEY must be a random secret of at least "
                    f"{MIN_PROD_SECRET_LENGTH} characters in prod"
                )
            if self.demo_login:
                raise ValueError("DEMO_LOGIN must be off in prod (password-free login)")
        return self

    # Convenience flag: True = talk to a Qdrant server, False = embedded Qdrant.
    @property
    def qdrant_is_remote(self) -> bool:
        return bool(self.qdrant_url)


# =============================================================================
# 4. ACCESS POINT - the rest of the app calls get_settings()
# =============================================================================
# @lru_cache means the .env file is read once and the same Settings object is reused.
# Tests call get_settings.cache_clear() to load fresh settings.
@lru_cache
def get_settings() -> Settings:
    return Settings()
