"""
FILE:         tests/unit/test_auth_api.py
WHAT IT TESTS: The login flow end to end over HTTP (app/api/auth.py +
              app/auth/dependencies.py), including role-spoofing attempts.
WHERE IT FITS: Phase 3.

Sections:
    LOGIN       correct / wrong credentials, no user enumeration
    WHO AM I    /auth/me returns exactly what the database says
    SPOOFING    attempts to gain more access than the database grants
"""

from fastapi.testclient import TestClient

from app.auth.models import User
from app.auth.schemas import AuthenticatedUser
from app.auth.tokens import create_access_token
from app.core.database import get_session_factory


def _login(client: TestClient, email: str, password: str, **extra):
    return client.post("/auth/login", data={"username": email, "password": password, **extra})


# =============================================================================
# LOGIN
# =============================================================================
# TEST 1: right email + password -> a bearer token.
def test_login_returns_token(client: TestClient, seeded) -> None:
    creds = seeded["u_engineer"]
    resp = _login(client, creds["email"], creds["password"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 3600
    assert body["access_token"].count(".") == 2  # header.claims.signature


# TEST 2: emails are case-insensitive.
def test_login_email_is_case_insensitive(client: TestClient, seeded) -> None:
    creds = seeded["u_engineer"]
    assert _login(client, creds["email"].upper(), creds["password"]).status_code == 200


# TEST 3: wrong password and unknown email give the SAME reply (no user enumeration).
def test_wrong_password_and_unknown_user_look_identical(client: TestClient, seeded) -> None:
    wrong_pw = _login(client, seeded["u_ceo"]["email"], "wrong-password")
    no_user = _login(client, "nobody@orbitra.example", "wrong-password")
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json() == no_user.json() == {"detail": "Incorrect email or password"}


# TEST 4: one persona's password doesn't work for another persona.
def test_password_is_per_user(client: TestClient, seeded) -> None:
    resp = _login(client, seeded["u_ceo"]["email"], seeded["u_intern"]["password"])
    assert resp.status_code == 401


# =============================================================================
# WHO AM I
# =============================================================================
# TEST 5: no token -> 401.
def test_me_requires_a_token(client: TestClient) -> None:
    resp = client.get("/auth/me")
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"


# TEST 6: each persona sees their own clearance and departments.
def test_me_returns_the_logged_in_user(client: TestClient, login) -> None:
    body = client.get("/auth/me", headers=login("u_cfo")).json()
    assert body["user_id"] == "u_cfo"
    assert body["clearance"] == 4
    assert sorted(body["departments"]) == ["executive", "finance"]
    assert "password" not in str(body).lower()


# =============================================================================
# SPOOFING - trying to get more access than the database grants
# =============================================================================
# SPOOF 1: send extra "role"/"clearance" fields at login -> ignored.
def test_extra_login_fields_cannot_raise_privileges(client: TestClient, seeded) -> None:
    creds = seeded["u_intern"]
    resp = _login(client, creds["email"], creds["password"], role="executive", clearance="4")
    token = resp.json()["access_token"]
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["role"] == "intern"
    assert me["clearance"] == 1


# SPOOF 2: a correctly signed token whose claims say clearance 4 (e.g. issued before a
# demotion) -> the server still uses the DATABASE's clearance (1).
def test_token_claims_are_not_trusted_over_the_database(client: TestClient, seeded) -> None:
    inflated = AuthenticatedUser(
        user_id="u_intern", email="x@orbitra.example", name="x", title="x",
        role="executive", clearance=4, departments=frozenset({"executive"}),
    )
    token, _ = create_access_token(inflated)
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["clearance"] == 1
    assert me["role"] == "intern"
    assert me["departments"] == ["engineering"]


# SPOOF 3: a valid token for a user who no longer exists -> 401.
def test_token_for_unknown_user_is_rejected(client: TestClient, seeded) -> None:
    ghost = AuthenticatedUser(
        user_id="u_ghost", email="g@orbitra.example", name="g", title="g",
        role="executive", clearance=4, departments=frozenset({"executive"}),
    )
    token, _ = create_access_token(ghost)
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


# SPOOF 4: disabling an account kills its existing tokens AND blocks new logins.
def test_disabled_account_is_locked_out(client: TestClient, login, seeded) -> None:
    headers = login("u_sales_rep")
    with get_session_factory()() as db:
        db.get(User, "u_sales_rep").is_active = False
        db.commit()
    assert client.get("/auth/me", headers=headers).status_code == 401
    creds = seeded["u_sales_rep"]
    assert _login(client, creds["email"], creds["password"]).status_code == 401


# SPOOF 5: garbage in the Authorization header -> 401, same generic message.
def test_garbage_token_is_rejected(client: TestClient) -> None:
    resp = client.get("/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Could not validate credentials"}
