"""
FILE:         scripts/seed_users.py
WHAT IT DOES: Creates a login account for each of the 8 demo personas.
WHERE IT FITS: Phase 3. Run once per database (local SQLite and/or Docker Postgres).
              Safe to re-run: existing users are updated, passwords are kept.
USED BY:      you, from the command line; tests call seed().

    python -m scripts.seed_users                                    # local SQLite
    python -m scripts.seed_users --database-url postgresql+psycopg://rag:rag_dev_password@localhost:5432/enterprise_rag

Passwords:
    Each persona gets a RANDOM password, written to data/org/dev_credentials.yaml.
    That file is git-ignored (never committed) and reused on later runs, so the same
    passwords work against every database you seed. Refuses to run when ENVIRONMENT=prod.
"""

import argparse
import os
import secrets
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from app.auth.personas import load_personas
from app.auth.service import upsert_user
from app.core.config import DATA_DIR, get_settings

CREDENTIALS_PATH = DATA_DIR / "org" / "dev_credentials.yaml"

_CREDENTIALS_HEADER = (
    "# LOCAL DEV ONLY - demo login passwords created by scripts/seed_users.py.\n"
    "# This file is git-ignored. Log in with `email` + `password`.\n"
)


# =============================================================================
# 1. PASSWORDS - reuse existing ones, generate the missing ones
# =============================================================================
def _load_credentials(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("users", {})


def _write_credentials(path: Path, creds: dict[str, dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump({"users": creds}, sort_keys=False)
    path.write_text(_CREDENTIALS_HEADER + body, encoding="utf-8")


# =============================================================================
# 2. SEED - create/update one account per persona
# =============================================================================
def seed(db: Session, credentials_path: Path = CREDENTIALS_PATH) -> dict[str, dict[str, str]]:
    if get_settings().environment == "prod":
        raise RuntimeError("refusing to create demo users with known passwords in prod")

    personas = load_personas()
    existing = _load_credentials(credentials_path)
    creds: dict[str, dict[str, str]] = {}

    for persona in personas.values():
        # Keep the old password if this persona already has one; else make a new one.
        password = existing.get(persona.user_id, {}).get("password") or secrets.token_urlsafe(12)
        creds[persona.user_id] = {"email": persona.email, "password": password}
        upsert_user(
            db,
            user_id=persona.user_id,
            email=persona.email,
            name=persona.name,
            title=persona.title,
            role=persona.role,
            clearance=persona.clearance,
            departments=persona.departments,
            password=password,  # hashed inside upsert_user; only the hash hits the DB
        )

    db.commit()
    _write_credentials(credentials_path, creds)
    return creds


# =============================================================================
# 3. COMMAND-LINE ENTRY POINT
# =============================================================================
def main() -> None:
    parser = argparse.ArgumentParser(description="Create demo login accounts.")
    parser.add_argument("--database-url", help="override DATABASE_URL (e.g. Docker Postgres)")
    parser.add_argument("--reset", action="store_true",
                        help="DEV ONLY: drop and recreate the users tables first "
                             "(needed after the users schema changes, e.g. a new role)")
    args = parser.parse_args()

    # Point the app's settings at the chosen database BEFORE anything connects.
    if args.database_url:
        os.environ["DATABASE_URL"] = args.database_url
        get_settings.cache_clear()

    from app.auth.models import User, UserDepartment
    from app.core.database import get_engine, get_session_factory, init_db

    if args.reset:
        if get_settings().environment == "prod":
            raise SystemExit("refusing to drop tables in prod")
        # Dev shortcut. A production system would ship a migration (e.g. Alembic) instead.
        for table in (UserDepartment.__table__, User.__table__):
            table.drop(get_engine(), checkfirst=True)
        print("Dropped users tables (dev reset).")

    init_db()  # make sure the tables exist
    with get_session_factory()() as db:
        creds = seed(db)

    print(f"Seeded {len(creds)} users. Passwords are in {CREDENTIALS_PATH} (git-ignored).")
    for user_id, c in creds.items():
        print(f"  {user_id:<18} {c['email']}")


if __name__ == "__main__":
    main()
