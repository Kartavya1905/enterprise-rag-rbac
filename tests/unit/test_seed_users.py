"""
FILE:         tests/unit/test_seed_users.py
WHAT IT TESTS: The demo-account seed script (scripts/seed_users.py) and the users tables.
WHERE IT FITS: Phase 3.
"""

import pytest
from sqlalchemy import select

from app.auth.models import User
from app.auth.personas import load_personas
from app.auth.service import upsert_user
from app.core.access import Clearance, Department
from app.core.database import get_session_factory
from scripts.seed_users import seed


# TEST 1: every persona becomes a user with the same clearance and departments.
def test_seed_creates_every_persona(seeded) -> None:
    personas = load_personas()
    with get_session_factory()() as db:
        users = {u.user_id: u for u in db.scalars(select(User))}
    assert users.keys() == personas.keys()
    for user_id, persona in personas.items():
        assert users[user_id].clearance == persona.clearance
        assert users[user_id].department_set == persona.departments


# TEST 2: only bcrypt hashes are stored - never the plain password.
def test_passwords_are_stored_hashed(seeded) -> None:
    with get_session_factory()() as db:
        user = db.get(User, "u_ceo")
    assert seeded["u_ceo"]["password"] not in user.password_hash
    assert user.password_hash.startswith("$2b$")  # bcrypt marker


# TEST 3: re-running the seed keeps the same passwords (re-uses the credentials file).
def test_reseeding_keeps_passwords(client, tmp_path) -> None:
    path = tmp_path / "creds.yaml"
    with get_session_factory()() as db:
        first = seed(db, path)
        second = seed(db, path)
    assert first == second


# TEST 4: the seed refuses to create demo users in production.
def test_seed_refuses_in_prod(client, tmp_path, monkeypatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setenv("ENVIRONMENT", "prod")
    get_settings.cache_clear()
    with get_session_factory()() as db, pytest.raises(RuntimeError):
        seed(db, tmp_path / "creds.yaml")


# TEST 5: "all" is a document-only value - a user cannot be put in department "all".
def test_user_cannot_belong_to_all_departments(client) -> None:
    with get_session_factory()() as db, pytest.raises(ValueError):
        upsert_user(
            db, user_id="u_bad", email="bad@orbitra.example", name="Bad", title="Bad",
            role="employee", clearance=Clearance.PUBLIC,
            departments=frozenset({Department.ALL}), password="whatever-123",
        )
