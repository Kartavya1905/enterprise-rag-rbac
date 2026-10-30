"""
FILE:         app/auth/service.py
WHAT IT DOES: The user operations: look a user up, check a login, create/update a user,
              and convert a database row into an AuthenticatedUser.
WHERE IT FITS: Phase 3. The "business logic" layer between the API routes and the tables.
USED BY:      api/auth.py (login), auth/dependencies.py (current user),
              scripts/seed_users.py (create users).
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import User, UserDepartment
from app.auth.passwords import burn_verification_time, hash_password, verify_password
from app.auth.schemas import AuthenticatedUser, Role
from app.core.access import Clearance, Department


def _normalize_email(email: str) -> str:
    return email.strip().lower()


# =============================================================================
# 1. LOOKUPS
# =============================================================================
def get_user(db: Session, user_id: str) -> User | None:
    return db.get(User, user_id)


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalars(select(User).where(User.email == _normalize_email(email))).first()


# =============================================================================
# 2. LOGIN CHECK - returns the user only if email, password AND status are all OK
# =============================================================================
def authenticate(db: Session, email: str, password: str) -> User | None:
    user = get_user_by_email(db, email)
    if user is None:
        burn_verification_time(password)  # same delay as a real check (no email probing)
        return None
    if not verify_password(password, user.password_hash):
        return None
    if not user.is_active:
        return None  # disabled accounts can't log in, even with the right password
    return user


# =============================================================================
# 3. ROW -> IDENTITY - the object every later phase uses for access decisions
# =============================================================================
def to_authenticated_user(user: User) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=user.user_id,
        email=user.email,
        name=user.name,
        title=user.title,
        role=user.role,
        clearance=Clearance(user.clearance),
        departments=user.department_set,
    )


# =============================================================================
# 4. CREATE OR UPDATE - used by the seed script (and later an admin API)
# =============================================================================
def upsert_user(
    db: Session,
    *,
    user_id: str,
    email: str,
    name: str,
    title: str,
    role: Role,
    clearance: Clearance,
    departments: frozenset[Department],
    password: str,
) -> User:
    # "all" is a document-only value; a person must belong to real departments.
    if not departments or Department.ALL in departments:
        raise ValueError(f"{user_id}: users need at least one real department (not 'all')")

    user = get_user(db, user_id) or User(user_id=user_id)
    user.email = _normalize_email(email)
    user.name, user.title, user.role = name, title, role
    user.clearance = int(clearance)
    user.password_hash = hash_password(password)
    user.is_active = True
    # Replace the department list (cascade deletes rows that are no longer listed).
    user.departments = [UserDepartment(department=d) for d in sorted(departments)]
    db.add(user)
    return user
