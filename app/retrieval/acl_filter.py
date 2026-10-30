"""
FILE:         app/retrieval/acl_filter.py
WHAT IT DOES: Translates "who is asking" into a Qdrant filter, so the DATABASE itself
              only returns chunks that user may read. Unauthorized chunks are never
              scored, never returned, never seen by the LLM.
WHERE IT FITS: Phase 6 - applied to EVERY retrieval path (dense AND sparse search).
USED BY:      retrieval/search.py, tests.

It is the same five rules as can_read() in app/core/access.py, written in Qdrant's
filter language. Tests check, for every persona and every chunk, that the filter and
can_read() give the same answer.

    can_read rule                         Qdrant filter
    -------------------------------------------------------------------------------
    1. denied_users contains user   ->    must_not: denied_users == user_id
    2. clearance too low            ->    must:     clearance_level <= user clearance
    3/4/5. "all" OR allowed OR dept ->    must: (should: departments any-of ["all", ...]
                                                  OR allowed_users == user_id)

The filter is built ONLY from the verified Principal (from the database, Phase 3) -
never from anything in the request body.
"""

from qdrant_client import models

from app.core.access import Department, Principal


def build_acl_filter(user: Principal) -> models.Filter:
    return models.Filter(
        must=[
            # Rule 2: clearance_level <= the user's clearance
            models.FieldCondition(
                key="clearance_level", range=models.Range(lte=int(user.clearance))
            ),
            # Rules 3-5: at least ONE of these must hold
            models.Filter(should=[
                # open to all departments, or shares a department with the user
                models.FieldCondition(
                    key="departments",
                    match=models.MatchAny(
                        any=[str(Department.ALL), *sorted(str(d) for d in user.departments)]
                    ),
                ),
                # named need-to-know grant
                models.FieldCondition(
                    key="allowed_users", match=models.MatchValue(value=user.user_id)
                ),
            ]),
        ],
        must_not=[
            # Rule 1: explicit block always wins
            models.FieldCondition(
                key="denied_users", match=models.MatchValue(value=user.user_id)
            ),
        ],
    )
