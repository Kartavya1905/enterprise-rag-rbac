"""
FILE:         app/core/access.py
WHAT IT DOES: THE ACCESS RULES - the single definition of "who may read what".
WHERE IT FITS: Phase 2 defined it. Every enforcement point built later must agree with
              `can_read`: the Qdrant search filter (Phase 6), the post-retrieval
              double-check (Phase 6) and column redaction (Phase 6). The RBAC leak tests
              (Phase 11) use it as the oracle - the "correct answer" to compare against.
              combine_acls() (Phase 4) merges a document label with a stricter column label.
USED BY:      auth/, ingestion/manifest.py, ingestion/chunker.py, scripts/, tests.

Rules, in order:
1. A user in `denied_users` is always refused (explicit deny wins).
2. The user's clearance must be >= the resource's clearance level. No grant bypasses this.
3. If the resource is open to `all` departments, access is granted.
4. If the user is in `allowed_users` (a need-to-know grant), access is granted.
5. Otherwise the user must belong to at least one of the resource's departments.
"""

from enum import IntEnum, StrEnum

from pydantic import BaseModel, Field


# =============================================================================
# 1. VOCABULARY - the clearance levels and departments that exist
# =============================================================================
# IntEnum so levels can be compared: Clearance.RESTRICTED > Clearance.INTERNAL.
class Clearance(IntEnum):
    PUBLIC = 1        # e.g. employee handbook
    INTERNAL = 2      # e.g. product roadmap
    CONFIDENTIAL = 3  # e.g. payroll
    RESTRICTED = 4    # e.g. board minutes


# StrEnum so values read naturally in YAML: departments: [hr, finance]
class Department(StrEnum):
    ALL = "all"  # special value: "every department" (only used on documents)
    ENGINEERING = "engineering"
    SALES = "sales"
    HR = "hr"
    FINANCE = "finance"
    EXECUTIVE = "executive"


# =============================================================================
# 2. THE TWO SIDES OF EVERY ACCESS DECISION
# =============================================================================
# WHO is asking - a logged-in user (from Phase 3: built from their verified token).
class Principal(BaseModel):
    """An authenticated identity, as far as access decisions are concerned."""

    user_id: str
    clearance: Clearance
    departments: frozenset[Department]


# WHAT they want to read - the access label on a document, a chunk, or a sheet column.
class ResourceACL(BaseModel):
    """Access rules attached to a document, a chunk, or a sheet column."""

    clearance_level: Clearance
    departments: list[Department] = Field(min_length=1)  # at least one department
    allowed_users: list[str] = Field(default_factory=list)  # named exceptions
    denied_users: list[str] = Field(default_factory=list)  # named blocks


# =============================================================================
# 3. THE DECISION - apply the five rules in order (see top of file)
# =============================================================================
def can_read(principal: Principal, acl: ResourceACL) -> bool:
    # Rule 1: explicit block always wins.
    if principal.user_id in acl.denied_users:
        return False
    # Rule 2: clearance too low -> refused, no matter what else is true.
    if principal.clearance < acl.clearance_level:
        return False
    # Rule 3: open to everyone (who has enough clearance).
    if Department.ALL in acl.departments:
        return True
    # Rule 4: named exception - lets a user past the department check only.
    if principal.user_id in acl.allowed_users:
        return True
    # Rule 5: user must share at least one department with the resource.
    return not principal.departments.isdisjoint(acl.departments)


# =============================================================================
# 4. COMBINING TWO LABELS - "must pass BOTH" as a single label
# =============================================================================
# Used for spreadsheet columns: a salary chunk must satisfy the DOCUMENT's label AND
# the COLUMN's stricter label. Search (Phase 6) filters on one label per chunk, so the
# two are merged here into one equivalent label.
class UnsupportedACLCombination(ValueError):
    """The two labels cannot be merged into one exactly-equivalent label."""


def combine_acls(outer: ResourceACL, inner: ResourceACL) -> ResourceACL:
    """Return one ACL that grants access exactly when BOTH outer and inner grant it.

    Exact only when at least one side is open to "all" departments (then that side's
    department check always passes and the other side's applies). Any other shape
    raises UnsupportedACLCombination instead of guessing - failing loudly is safer than
    a label that is subtly too loose.
    """
    if Department.ALL in outer.departments:
        departments, allowed = inner.departments, inner.allowed_users
    elif Department.ALL in inner.departments:
        departments, allowed = outer.departments, outer.allowed_users
    else:
        raise UnsupportedACLCombination(
            "one of the two labels must be open to 'all' departments"
        )
    return ResourceACL(
        clearance_level=max(outer.clearance_level, inner.clearance_level),  # stricter wins
        departments=list(departments),
        allowed_users=list(allowed),
        denied_users=sorted(set(outer.denied_users) | set(inner.denied_users)),  # both
    )
