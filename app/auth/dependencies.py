"""
FILE:         app/auth/dependencies.py
WHAT IT DOES: get_current_user() - the gatekeeper every protected route depends on. It
              turns "Authorization: Bearer <token>" into a verified AuthenticatedUser,
              or rejects the request with HTTP 401.
WHERE IT FITS: Phase 3. From Phase 6 on, the user it returns is what the access filter
              is built from - so this is where "who is asking" is decided, once.
USED BY:      api/auth.py (/auth/me), and later every query/ingest/admin route.

Usage in a route:
    @router.get("/something")
    def something(user: CurrentUser): ...
"""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.auth.schemas import AuthenticatedUser
from app.auth.service import get_user, to_authenticated_user
from app.auth.tokens import TokenError, decode_access_token
from app.core.database import DbSession

# Reads the token from the "Authorization: Bearer ..." header (401 if missing).
# tokenUrl also wires up the "Authorize" button on the /docs page.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def _unauthorized() -> HTTPException:
    # One generic message for every failure: never tell an attacker WHICH check failed.
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)], db: DbSession
) -> AuthenticatedUser:
    # --- STEP 1: is the token genuine, unexpired, and meant for this API? ---
    try:
        claims = decode_access_token(token)
    except TokenError as exc:
        raise _unauthorized() from exc

    # --- STEP 2: does that user still exist and is the account active? ---
    user = get_user(db, claims["sub"])
    if user is None or not user.is_active:
        raise _unauthorized()

    # --- STEP 3: build the identity from the DATABASE, not from the token's claims ---
    # If someone was demoted or moved department after logging in, their old token's
    # "clearance"/"departments" claims are stale. The database is the source of truth.
    return to_authenticated_user(user)


# Shorthand for route signatures: `def route(user: CurrentUser): ...`
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]


# =============================================================================
# ADMIN GATE (Phase 8) - document management routes depend on this
# =============================================================================
def require_admin(user: CurrentUser) -> AuthenticatedUser:
    # Role comes from the DATABASE (via get_current_user), never from the request.
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Administrator role required")
    return user


AdminUser = Annotated[AuthenticatedUser, Depends(require_admin)]
