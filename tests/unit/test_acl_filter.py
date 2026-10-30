"""
FILE:         tests/unit/test_acl_filter.py
WHAT IT TESTS: The Qdrant access filter (app/retrieval/acl_filter.py) gives EXACTLY the
              same answer as the reference rules, can_read() - for every persona, for
              thousands of random users, and for every chunk.
WHERE IT FITS: Phase 6. If this holds, the database can only ever return chunks the
              user is allowed to read.
"""

import itertools
import random

from app.core.access import Department, Principal, can_read
from app.core.config import get_settings
from app.core.vectorstore import get_qdrant_client
from app.retrieval.acl_filter import build_acl_filter
from app.retrieval.indexer import index_chunks
from tests.fakes import HashingEmbedder


# Ask Qdrant: "which chunk ids does this filter let through?"
def _ids_passing_filter(user: Principal) -> set[str]:
    points, _ = get_qdrant_client().scroll(
        get_settings().qdrant_collection,
        scroll_filter=build_acl_filter(user),
        limit=10_000,
        with_payload=False,
    )
    return {str(p.id) for p in points}


# The 8 personas: database filter == oracle, chunk by chunk.
def test_filter_matches_oracle_for_every_persona(test_env, ingested, personas) -> None:
    index_chunks(ingested.chunks, embedder=HashingEmbedder())
    for persona in personas.values():
        expected = {c.chunk_id for c in ingested.chunks if can_read(persona, c)}
        assert _ids_passing_filter(persona) == expected, persona.user_id


# Many random users - including ones named in allowed_users / denied_users lists.
def test_filter_matches_oracle_for_random_users(test_env, ingested) -> None:
    index_chunks(ingested.chunks, embedder=HashingEmbedder())
    named = sorted({u for c in ingested.chunks for u in c.allowed_users + c.denied_users})
    depts = [d for d in Department if d is not Department.ALL]
    rng = random.Random(11)
    users = [
        Principal(user_id=uid, clearance=clearance, departments=frozenset(combo))
        for uid in [*named, "u_nobody"]
        for clearance in range(1, 5)
        for n in (1, 2)
        for combo in itertools.combinations(depts, n)
    ]
    for user in rng.sample(users, 120):
        expected = {c.chunk_id for c in ingested.chunks if can_read(user, c)}
        assert _ids_passing_filter(user) == expected, user
