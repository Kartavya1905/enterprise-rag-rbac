"""
FILE:         tests/unit/test_ops_scripts.py
WHAT IT TESTS: The deployment tools: create_user (real accounts for production) and
               bootstrap's safety stops. smoke_test and demo talk to a RUNNING server, so
               they're exercised by CI's docker job, not here.
WHERE IT FITS: Phase 12.
"""

import re
import sys

import pytest

from scripts import bootstrap, create_user

JANE = ["--user-id", "u_jdoe", "--email", "jane.doe@example.com", "--name", "Jane Doe",
        "--title", "Financial Analyst", "--role", "finance"]


def _create(monkeypatch, capsys, *args: str) -> str:
    """Run create_user with these arguments; return the password it printed."""
    monkeypatch.setattr(sys, "argv", ["create_user", *args])
    create_user.main()
    return re.search(r"Password \(shown once.*\): (\S+)", capsys.readouterr().out).group(1)


# TEST 1: the new account can log in, and the server reports the clearance we set.
def test_create_user_makes_a_working_account(client, monkeypatch, capsys) -> None:
    password = _create(monkeypatch, capsys, *JANE, "--clearance", "3",
                       "--department", "finance")
    r = client.post("/auth/login",
                    data={"username": "jane.doe@example.com", "password": password})
    assert r.status_code == 200
    me = client.get("/auth/me",
                    headers={"Authorization": f"Bearer {r.json()['access_token']}"}).json()
    assert me["clearance"] == 3 and me["departments"] == ["finance"]


# TEST 2: running it again updates the account AND replaces the password.
def test_create_user_again_updates_and_resets(client, monkeypatch, capsys) -> None:
    old = _create(monkeypatch, capsys, *JANE, "--clearance", "3", "--department", "finance")
    new = _create(monkeypatch, capsys, *JANE, "--clearance", "2", "--department", "finance",
                  "--department", "sales")
    assert old != new
    assert client.post("/auth/login", data={"username": "jane.doe@example.com",
                                            "password": old}).status_code == 401
    r = client.post("/auth/login", data={"username": "jane.doe@example.com", "password": new})
    me = client.get("/auth/me",
                    headers={"Authorization": f"Bearer {r.json()['access_token']}"}).json()
    assert me["clearance"] == 2 and sorted(me["departments"]) == ["finance", "sales"]


# TEST 3: "all" is a document-only value and is rejected before anything is written.
def test_create_user_rejects_all_department(client, monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["create_user", *JANE, "--clearance", "1",
                                      "--department", "all"])
    with pytest.raises(SystemExit):
        create_user.main()


# TEST 4: create_user works in prod - it's the ONLY way to add accounts there.
def test_create_user_works_in_prod(client, monkeypatch, capsys) -> None:
    from app.core.config import get_settings

    monkeypatch.setenv("ENVIRONMENT", "prod")
    get_settings.cache_clear()
    assert _create(monkeypatch, capsys, *JANE, "--clearance", "3", "--department", "finance")


# TEST 5: bootstrap stops at once, with instructions, when there are no documents.
def test_bootstrap_stops_without_a_manifest(test_env, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DOCUMENTS_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["bootstrap", "--skip-llm-check"])
    with pytest.raises(SystemExit, match="generate_dataset"):
        bootstrap.main()
