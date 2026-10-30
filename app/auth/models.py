"""
FILE:         app/auth/models.py
WHAT IT DOES: Defines the database tables that store users:
                users             one row per person (clearance, role, password HASH ...)
                user_departments  which departments each user belongs to (many-to-many)
WHERE IT FITS: Phase 3. These tables are the SOURCE OF TRUTH for identity: on every
              request the app re-reads the user from here, never trusting the token alone.
USED BY:      auth/service.py, core/database.py (init_db creates the tables).

    users                                  user_departments
    +-------------+---------------+        +-------------+-------------+
    | user_id  PK | password_hash |  1   * | user_id  FK | department  |
    | email  UNIQ | clearance 1-4 |--------| (PK pair)   | (PK pair)   |
    | name, title | role          |        +-------------+-------------+
    | is_active   | created_at    |
    +-------------+---------------+
"""

from datetime import datetime
from typing import get_args

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.auth.schemas import Role
from app.core.access import Department
from app.core.database import Base

_ROLE_VALUES = ", ".join(f"'{r}'" for r in get_args(Role))


# =============================================================================
# 1. USERS TABLE
# =============================================================================
class User(Base):
    __tablename__ = "users"

    # --- identity ---
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)  # e.g. "u_intern"
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)  # login name
    name: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(255))

    # --- what drives access decisions ---
    role: Mapped[str] = mapped_column(String(32))
    clearance: Mapped[int] = mapped_column(Integer)

    # --- credentials and status ---
    # Only a bcrypt HASH is stored - the real password is never saved anywhere.
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True)  # False = account disabled
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # --- link to the user's departments (loaded together with the user) ---
    departments: Mapped[list["UserDepartment"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )

    # --- database-level guards: bad values are rejected even if app code has a bug ---
    __table_args__ = (
        CheckConstraint("clearance BETWEEN 1 AND 4", name="ck_users_clearance"),
        CheckConstraint(f"role IN ({_ROLE_VALUES})", name="ck_users_role"),
    )

    @property
    def department_set(self) -> frozenset[Department]:
        return frozenset(d.department for d in self.departments)


# =============================================================================
# 2. USER_DEPARTMENTS TABLE - a user can belong to several departments
# =============================================================================
class UserDepartment(Base):
    __tablename__ = "user_departments"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True
    )
    # Stored as plain text ("hr"), but only values from the Department enum are accepted.
    department: Mapped[Department] = mapped_column(
        SAEnum(
            Department,
            native_enum=False,
            length=32,
            values_callable=lambda enum: [member.value for member in enum],
            validate_strings=True,
        ),
        primary_key=True,
    )

    user: Mapped[User] = relationship(back_populates="departments")
