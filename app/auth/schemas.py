"""
FILE:         app/auth/schemas.py
WHAT IT DOES: The shapes of identity data passed around in memory and over the API:
              who a logged-in user is, and what the login endpoint returns.
WHERE IT FITS: Phase 3. `AuthenticatedUser` is the object every later phase receives to
              decide what the user may see (it IS a Principal, so it goes straight into
              can_read() in app/core/access.py).
USED BY:      auth/service.py, auth/dependencies.py, auth/personas.py, api/auth.py.
"""

from typing import Literal

from pydantic import BaseModel

from app.core.access import Principal

# =============================================================================
# 1. ROLES - job roles that exist in the company
# =============================================================================
# Note: what a user may READ is decided by clearance + departments (access.py), NOT role.
# Role is descriptive (shown in the UI, recorded in the audit log) - with one exception:
# "admin" may MANAGE documents (upload, change ACLs, delete) through /admin (Phase 8).
Role = Literal["intern", "employee", "manager", "hr", "finance", "executive", "admin"]


# =============================================================================
# 2. THE LOGGED-IN USER - built from the DATABASE on every request
# =============================================================================
# Inherits user_id, clearance, departments from Principal and adds display details.
class AuthenticatedUser(Principal):
    email: str
    name: str
    title: str
    role: Role


# =============================================================================
# 3. LOGIN RESPONSE - what POST /auth/login returns
# =============================================================================
class TokenResponse(BaseModel):
    access_token: str  # the JWT; send it back as "Authorization: Bearer <token>"
    token_type: Literal["bearer"] = "bearer"
    expires_in: int  # seconds until the token stops working
