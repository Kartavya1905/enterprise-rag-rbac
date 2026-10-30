"""
FILE:         tests/unit/test_access_policy.py
WHAT IT TESTS: Each of the five access rules in can_read() (app/core/access.py), one at a
              time, using tiny made-up users and resources.
WHERE IT FITS: Phase 2. If these pass, the "oracle" that later phases are checked against
              is itself correct.
"""

import itertools
import random

import pytest

from app.core.access import (
    Clearance,
    Department,
    Principal,
    ResourceACL,
    UnsupportedACLCombination,
    can_read,
    combine_acls,
)


# --- Helpers: build a test user / a test access label in one short line ---
def user(clearance: int, *departments: str, user_id: str = "u_test") -> Principal:
    return Principal(user_id=user_id, clearance=clearance, departments=frozenset(departments))


def acl(clearance: int, *departments: str, allowed=(), denied=()) -> ResourceACL:
    return ResourceACL(clearance_level=clearance, departments=list(departments),
                       allowed_users=list(allowed), denied_users=list(denied))


# RULES 2 + 3: "all departments" still requires enough clearance.
def test_open_to_all_departments_needs_only_clearance() -> None:
    assert can_read(user(1, "sales"), acl(1, "all"))
    assert not can_read(user(1, "sales"), acl(2, "all"))


# RULE 5: otherwise the user must share a department.
def test_department_must_match() -> None:
    assert can_read(user(3, "finance"), acl(3, "hr", "finance"))
    assert not can_read(user(3, "engineering"), acl(3, "hr", "finance"))


# RULE 2: higher clearance can read lower levels.
def test_higher_clearance_reads_lower_levels() -> None:
    assert can_read(user(4, "hr"), acl(2, "hr"))


# RULE 4: a named grant skips the department check, but NEVER the clearance check.
def test_allowed_user_bypasses_department_but_not_clearance() -> None:
    assert can_read(user(3, "engineering", user_id="u_x"), acl(3, "finance", allowed=["u_x"]))
    assert not can_read(user(2, "engineering", user_id="u_x"), acl(3, "finance", allowed=["u_x"]))


# RULE 1: a named block beats everything, even top clearance or a named grant.
def test_explicit_deny_wins_over_everything() -> None:
    assert not can_read(user(4, "hr", user_id="u_x"), acl(1, "all", denied=["u_x"]))
    assert not can_read(user(4, "hr", user_id="u_x"),
                        acl(3, "hr", allowed=["u_x"], denied=["u_x"]))


# SCHEMA: an access label with no departments is invalid.
def test_acl_requires_at_least_one_department() -> None:
    with pytest.raises(ValueError):
        acl(1)


# SCHEMA: plain values from YAML (4, "hr") turn into the right enum members.
def test_enums_parse_from_plain_values() -> None:
    assert Clearance(4) is Clearance.RESTRICTED
    assert Department("hr") is Department.HR


# =============================================================================
# combine_acls (Phase 4) - merged label must behave EXACTLY like "pass both"
# =============================================================================
_REAL_DEPTS = [d for d in Department if d is not Department.ALL]
_USERS = ["u_a", "u_b", "u_c"]


def _random_acl(rng: random.Random, open_to_all: bool) -> ResourceACL:
    depts = ["all"] if open_to_all else rng.sample(_REAL_DEPTS, rng.randint(1, 3))
    return ResourceACL(
        clearance_level=rng.randint(1, 4),
        departments=depts,
        allowed_users=rng.sample(_USERS, rng.randint(0, 2)),
        denied_users=rng.sample(_USERS, rng.randint(0, 1)),
    )


# Every possible user (3 ids x 4 clearances x every department combination).
_ALL_PRINCIPALS = [
    Principal(user_id=uid, clearance=c, departments=frozenset(depts))
    for uid in _USERS
    for c in range(1, 5)
    for n in range(1, 3)
    for depts in itertools.combinations(_REAL_DEPTS, n)
]


# PROPERTY TEST: 400 random label pairs x every possible user -> merged == both.
def test_combined_acl_equals_passing_both() -> None:
    rng = random.Random(7)
    for _ in range(400):
        outer_all = rng.random() < 0.5
        outer = _random_acl(rng, open_to_all=outer_all)
        inner = _random_acl(rng, open_to_all=not outer_all)
        merged = combine_acls(outer, inner)
        for p in _ALL_PRINCIPALS:
            assert can_read(p, merged) == (can_read(p, outer) and can_read(p, inner))


# Shapes that cannot be merged exactly are refused, never approximated.
def test_unmergeable_acls_are_refused() -> None:
    with pytest.raises(UnsupportedACLCombination):
        combine_acls(acl(2, "hr"), acl(3, "finance"))
