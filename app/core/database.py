"""
FILE:         app/core/database.py
WHAT IT DOES: Opens the connection to the relational database (SQLite locally, Postgres in
              Docker) and hands out "sessions" - short-lived conversations with the DB.
WHERE IT FITS: Phase 1 - foundation. From Phase 3 it stores users and roles; from Phase 9
              the audit log.
USED BY:      api/health.py, api/auth.py, auth/dependencies.py, scripts/seed_users.py,
              main.py (init_db at startup), and later the audit code.

Flow:  settings.database_url  ->  get_engine() (connection pool)
                              ->  get_session_factory()  ->  get_db() (one session/request)
       init_db()  ->  creates the tables (users, user_departments, documents,
                      audit_events) if missing
"""

from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings


# =============================================================================
# 1. BASE CLASS FOR TABLES
# =============================================================================
# Every database table we define later (users, documents, audit_log ...) inherits
# from Base, so SQLAlchemy knows about all of them.
class Base(DeclarativeBase):
    """Base class for all ORM models (users, documents, audit log, ...)."""


# =============================================================================
# 2. THE ENGINE - the app's single connection pool to the database
# =============================================================================
@lru_cache  # created once, then reused
def get_engine() -> Engine:
    url = get_settings().database_url
    # SQLite needs this flag so FastAPI's worker threads can share the connection.
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    # In-memory SQLite (tests): every new connection would be a NEW empty database, so
    # StaticPool keeps one single connection that all threads share.
    in_memory = url in ("sqlite://", "sqlite:///:memory:")
    pool = {"poolclass": StaticPool} if in_memory else {}
    # pool_pre_ping: test each connection before use, so a restarted DB doesn't break us.
    return create_engine(url, pool_pre_ping=True, connect_args=connect_args, **pool)


# =============================================================================
# 3. THE SESSION FACTORY - a template for creating sessions
# =============================================================================
@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


# =============================================================================
# 4. ONE SESSION PER REQUEST - used by API routes via FastAPI's Depends()
# =============================================================================
def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    session = get_session_factory()()
    try:
        yield session  # the route handler uses the session here
    finally:
        session.close()  # always closed, even if the route raised an error


# Shorthand for route signatures: `def route(db: DbSession): ...`
DbSession = Annotated[Session, Depends(get_db)]


# =============================================================================
# 5. CREATE TABLES - called at app startup and by the seed script
# =============================================================================
# create_all only creates tables that don't exist yet; it never deletes data.
# (A larger project would use migrations, e.g. Alembic, to evolve existing tables.)
def init_db() -> None:
    import app.audit.models  # noqa: F401 - the `audit_events` log (Phase 9)
    import app.auth.models  # noqa: F401 - importing registers the tables on Base
    import app.ingestion.models  # noqa: F401 - the `documents` registry (Phase 4)

    Base.metadata.create_all(get_engine())
