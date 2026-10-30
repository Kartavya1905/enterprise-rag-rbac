"""
FILE:         app/retrieval/collection.py
WHAT IT DOES: Creates (or checks) the Qdrant collection that stores the chunks, and the
              PAYLOAD INDEXES that make access-filtered search fast and exact.
WHERE IT FITS: Phase 5. Called before indexing; Phase 6 searches this collection.
USED BY:      retrieval/indexer.py, tests.

One collection, every chunk = one "point":
    point.id       = chunk_id (stable UUID)
    point.vector   = {"dense": [384 numbers], "sparse": {word ids: weights}}
    point.payload  = the chunk's text + ACL + metadata (everything in Chunk)

Payload indexes are like database indexes on the ACL fields. Phase 6 filters EVERY search
by clearance_level / departments / allowed_users / denied_users, so these must be indexed.
"""

import warnings

from qdrant_client import QdrantClient, models

DENSE = "dense"  # name of the meaning vector
SPARSE = "sparse"  # name of the keyword (BM25) vector

# field -> index type. INTEGER supports range filters (clearance_level <= 3);
# KEYWORD supports exact / any-of matches (departments contains "hr").
PAYLOAD_INDEXES: dict[str, models.PayloadSchemaType] = {
    # --- access control (Phase 6 filters on these) ---
    "clearance_level": models.PayloadSchemaType.INTEGER,
    "departments": models.PayloadSchemaType.KEYWORD,
    "allowed_users": models.PayloadSchemaType.KEYWORD,
    "denied_users": models.PayloadSchemaType.KEYWORD,
    # --- housekeeping (indexer) and browsing ---
    "doc_id": models.PayloadSchemaType.KEYWORD,
    "index_fingerprint": models.PayloadSchemaType.KEYWORD,
    "classification": models.PayloadSchemaType.KEYWORD,
    "source_type": models.PayloadSchemaType.KEYWORD,
}


class CollectionMismatch(RuntimeError):
    """The existing collection was built for a different embedding model size."""


def ensure_collection(
    client: QdrantClient, name: str, dense_dim: int, recreate: bool = False
) -> bool:
    """Make sure the collection exists with the right shape. Returns True if created."""
    # --- STEP 1: optionally start from scratch ---
    exists = client.collection_exists(name)
    if exists and recreate:
        client.delete_collection(name)
        exists = False

    # --- STEP 2: create it, or check the existing one matches the model ---
    if not exists:
        client.create_collection(
            name,
            vectors_config={
                # Cosine similarity: compares direction (meaning), not length.
                DENSE: models.VectorParams(size=dense_dim, distance=models.Distance.COSINE),
            },
            sparse_vectors_config={
                # IDF: rare words (e.g. "HR-2026-014") count more than common ones ("the").
                SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF),
            },
        )
    else:
        size = client.get_collection(name).config.params.vectors[DENSE].size
        if size != dense_dim:
            raise CollectionMismatch(
                f"collection '{name}' has {size}-dim vectors but the model makes "
                f"{dense_dim}-dim ones; re-run indexing with --recreate"
            )

    # --- STEP 3: payload indexes (creating an existing index is a harmless no-op) ---
    # Embedded/in-memory Qdrant (local dev, tests) filters correctly without them and
    # warns that they have no effect; the Qdrant server (Docker) uses them for speed.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Payload indexes have no effect")
        for field, schema in PAYLOAD_INDEXES.items():
            client.create_payload_index(name, field_name=field, field_schema=schema)
    return not exists
