"""
FILE:         tests/unit/test_tokens.py
WHAT IT TESTS: Creating and verifying JWTs (app/auth/tokens.py), including forged,
              tampered, unsigned, expired and wrong-audience tokens.
WHERE IT FITS: Phase 3.
"""

import base64
import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.auth.schemas import AuthenticatedUser
from app.auth.tokens import TokenError, create_access_token, decode_access_token
from tests.conftest import TEST_JWT_SECRET

INTERN = AuthenticatedUser(
    user_id="u_intern", email="aarav.mehta@orbitra.example", name="Aarav Mehta",
    title="Intern", role="intern", clearance=1, departments=frozenset({"engineering"}),
)


def _claims(**overrides) -> dict:
    now = datetime.now(UTC)
    base = {"sub": "u_intern", "iss": "enterprise-rag", "aud": "enterprise-rag-api",
            "iat": now, "exp": now + timedelta(minutes=5), "clearance": 1}
    return base | overrides


# =============================================================================
# HAPPY PATH
# =============================================================================
# TEST 1: a token we create decodes back to the same user and claims.
def test_round_trip(test_env: None) -> None:
    token, expires_in = create_access_token(INTERN)
    claims = decode_access_token(token)
    assert claims["sub"] == "u_intern"
    assert claims["clearance"] == 1
    assert claims["departments"] == ["engineering"]
    assert expires_in == 60 * 60


# =============================================================================
# ATTACKS - every one of these must be rejected
# =============================================================================
# ATTACK 1: attacker signs their own token with a key they made up.
def test_token_signed_with_another_key_is_rejected(test_env: None) -> None:
    forged = jwt.encode(_claims(clearance=4), "attacker-key-" + "y" * 40, algorithm="HS256")
    with pytest.raises(TokenError):
        decode_access_token(forged)


# ATTACK 2: attacker edits the claims of a real token (clearance 1 -> 4), keeps signature.
def test_tampered_claims_are_rejected(test_env: None) -> None:
    token, _ = create_access_token(INTERN)
    header, payload, signature = token.split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    claims["clearance"] = 4
    new_payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    with pytest.raises(TokenError):
        decode_access_token(f"{header}.{new_payload}.{signature}")


# ATTACK 3: the "alg: none" trick - an unsigned token.
def test_unsigned_alg_none_token_is_rejected(test_env: None) -> None:
    unsigned = jwt.encode(_claims(clearance=4), key=None, algorithm="none")
    with pytest.raises(TokenError):
        decode_access_token(unsigned)


# ATTACK 4: replaying an old, expired token.
def test_expired_token_is_rejected(test_env: None) -> None:
    token, _ = create_access_token(INTERN, expires_delta=timedelta(seconds=-1))
    with pytest.raises(TokenError):
        decode_access_token(token)


# ATTACK 5: a genuine signature, but the token was issued for a different service.
def test_wrong_audience_is_rejected(test_env: None) -> None:
    other = jwt.encode(_claims(aud="some-other-api"), TEST_JWT_SECRET, algorithm="HS256")
    with pytest.raises(TokenError):
        decode_access_token(other)


# ATTACK 6: not a JWT at all.
def test_garbage_is_rejected(test_env: None) -> None:
    with pytest.raises(TokenError):
        decode_access_token("not-a-jwt")
