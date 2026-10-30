"""
FILE:         app/auth/passwords.py
WHAT IT DOES: Turns passwords into one-way bcrypt hashes, and checks a password against a
              stored hash. The real password is never stored.
WHERE IT FITS: Phase 3. Used when creating users (seed) and when logging in.
USED BY:      auth/service.py.

Why bcrypt?  It is deliberately SLOW (tunable via PASSWORD_HASH_ROUNDS) and salted, so a
leaked database cannot be cracked quickly or with precomputed tables.
"""

from functools import lru_cache

import bcrypt

from app.core.config import get_settings

# bcrypt only looks at the first 72 bytes of a password. Longer ones are rejected rather
# than silently truncated (two different long passwords would otherwise "match").
MAX_PASSWORD_BYTES = 72


# =============================================================================
# 1. HASH - used when a user is created or their password changes
# =============================================================================
def hash_password(password: str) -> str:
    raw = password.encode("utf-8")
    if len(raw) > MAX_PASSWORD_BYTES:
        raise ValueError(f"password must be at most {MAX_PASSWORD_BYTES} bytes")
    salt = bcrypt.gensalt(rounds=get_settings().password_hash_rounds)  # random per password
    return bcrypt.hashpw(raw, salt).decode("ascii")


# =============================================================================
# 2. VERIFY - used at login
# =============================================================================
def verify_password(password: str, password_hash: str) -> bool:
    raw = password.encode("utf-8")
    if len(raw) > MAX_PASSWORD_BYTES:
        return False
    # checkpw re-hashes with the salt stored inside password_hash and compares safely.
    return bcrypt.checkpw(raw, password_hash.encode("ascii"))


# =============================================================================
# 3. TIMING DEFENSE - make "unknown email" as slow as "wrong password"
# =============================================================================
# Without this, an attacker could time login responses to discover which emails exist
# (unknown email = instant reply, real email = slow bcrypt check).
@lru_cache
def _dummy_hash() -> str:
    return hash_password("dummy-password-for-timing")


def burn_verification_time(password: str) -> None:
    verify_password(password, _dummy_hash())
