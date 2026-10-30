"""
FILE:         app/auth/tokens.py
WHAT IT DOES: Creates and verifies JWT access tokens - the signed "wristband" a user gets
              at login and shows on every later request.
WHERE IT FITS: Phase 3. Created by POST /auth/login; verified by get_current_user() on
              every protected request.
USED BY:      api/auth.py (create), auth/dependencies.py (verify).

A JWT has three dot-separated parts:   header . claims . signature
  - claims    = readable data (who, clearance, expiry ...). NOT encrypted - anyone can
                read them, so never put secrets in a token.
  - signature = HMAC of the first two parts with JWT_SECRET_KEY. Changing ANY claim
                (e.g. clearance 1 -> 4) breaks the signature, and the token is rejected.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from app.auth.schemas import AuthenticatedUser
from app.core.config import get_settings


class TokenError(Exception):
    """The token is missing, malformed, forged, expired, or not meant for this API."""


# =============================================================================
# 1. CREATE - called once at login
# =============================================================================
def create_access_token(
    user: AuthenticatedUser, expires_delta: timedelta | None = None
) -> tuple[str, int]:
    """Return (token, seconds until expiry)."""
    settings = get_settings()
    lifetime = expires_delta or timedelta(minutes=settings.jwt_expire_minutes)
    now = datetime.now(UTC)

    claims: dict[str, Any] = {
        # --- standard claims: who / issued by / for whom / when ---
        "sub": user.user_id,  # subject = the user this token belongs to
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": now,  # issued at
        "nbf": now,  # not valid before
        "exp": now + lifetime,  # expires at
        "jti": uuid.uuid4().hex,  # unique token id (useful for audit / revocation later)
        # --- display claims for the frontend. The SERVER never trusts these for access
        #     decisions; it re-reads the user from the database on every request. ---
        "role": user.role,
        "clearance": int(user.clearance),
        "departments": sorted(str(d) for d in user.departments),
    }
    token = jwt.encode(
        claims, settings.jwt_secret_key.get_secret_value(), algorithm=settings.jwt_algorithm
    )
    return token, int(lifetime.total_seconds())


# =============================================================================
# 2. VERIFY - called on every protected request
# =============================================================================
def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        return jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            # Only our algorithm is accepted. This blocks the classic "alg: none" attack,
            # where an attacker sends an unsigned token and hopes it is trusted.
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["sub", "exp", "iat", "iss", "aud"]},
        )
    except jwt.InvalidTokenError as exc:  # bad signature, expired, wrong aud/iss, garbage
        raise TokenError(type(exc).__name__) from exc
