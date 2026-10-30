"""
FILE:         app/api/auth.py
WHAT IT DOES: The login endpoints.
                POST /auth/login       -> email + password in, signed JWT out
                GET  /auth/me          -> "who am I?" (requires a valid token)
                GET  /auth/demo-users  -> DEV ONLY persona list for the UI switcher
                POST /auth/demo-login  -> DEV ONLY password-free login (DEMO_LOGIN=true)
WHERE IT FITS: Phase 3. The frontend (Phase 10) logs in here and sends the token with
              every question it asks.
USED BY:      main.py registers the router; tests/unit/test_auth_api.py tests it.

Try it: open http://localhost:8000/docs, click "Authorize", enter a persona's email as
username and its password from data/org/dev_credentials.yaml.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.audit import service as audit
from app.auth.dependencies import CurrentUser
from app.auth.models import User
from app.auth.schemas import AuthenticatedUser, TokenResponse
from app.auth.service import authenticate, get_user, to_authenticated_user
from app.auth.tokens import create_access_token
from app.core.config import get_settings
from app.core.database import DbSession
from app.core.rate_limit import limit_per_ip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


# =============================================================================
# 1. LOGIN
# =============================================================================
# Uses the standard OAuth2 "password" form (fields: username, password), sent as
# form data. "username" holds the email. The form has NO role/clearance fields, so a
# client cannot ask for more access - anything extra it sends is simply ignored.
@router.post("/login", response_model=TokenResponse,
             dependencies=[Depends(limit_per_ip("login"))])  # slows password guessing
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], db: DbSession,
          request: Request) -> TokenResponse:
    # --- STEP 1: check email + password + account status ---
    user = authenticate(db, form.username, form.password)
    if user is None:
        # Never log the password. Same message for "no such user" and "wrong password".
        logger.warning("Failed login attempt for username=%r", form.username[:254])
        audit.record("login", outcome="failed", request=request,
                     detail={"attempted_username": form.username[:254]})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # --- STEP 2: issue a signed token describing the user as the DATABASE knows them ---
    identity = to_authenticated_user(user)
    token, expires_in = create_access_token(identity)
    logger.info("User %s logged in", user.user_id)
    audit.record("login", outcome="ok", user=identity, request=request)
    return TokenResponse(access_token=token, expires_in=expires_in)


# =============================================================================
# 2. WHO AM I
# =============================================================================
# CurrentUser runs get_current_user(): verifies the token, then reloads the user from
# the database. What comes back is exactly what access decisions will use.
@router.get("/me", response_model=AuthenticatedUser)
def me(user: CurrentUser) -> AuthenticatedUser:
    return user


# =============================================================================
# 3. DEMO LOGIN (Phase 10) - DEV ONLY, off unless DEMO_LOGIN=true
# =============================================================================
# Powers the one-click persona switcher in the web UI, so a demo never needs passwords
# in the browser. When the setting is off, both routes answer 404 as if they did not
# exist; prod refuses to start with it on (config.py). Every use is audited.
class DemoLoginRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=64)


def _demo_enabled() -> None:
    if not get_settings().demo_login:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")


@router.get("/demo-users", response_model=list[AuthenticatedUser],
            dependencies=[Depends(_demo_enabled)])
def demo_users(db: DbSession) -> list[AuthenticatedUser]:
    users = db.scalars(select(User).where(User.is_active).order_by(User.clearance, User.user_id))
    return [to_authenticated_user(u) for u in users]


@router.post("/demo-login", response_model=TokenResponse,
             dependencies=[Depends(_demo_enabled), Depends(limit_per_ip("login"))])
def demo_login(body: DemoLoginRequest, db: DbSession, request: Request) -> TokenResponse:
    user = get_user(db, body.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown user")
    identity = to_authenticated_user(user)
    token, expires_in = create_access_token(identity)
    audit.record("login", outcome="ok", user=identity, request=request,
                 detail={"method": "demo_login"})
    return TokenResponse(access_token=token, expires_in=expires_in)
