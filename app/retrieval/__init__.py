"""
PACKAGE: app.retrieval - finding chunks the user is ALLOWED to see.

    embeddings.py   text -> dense (meaning) + sparse (keyword) vectors, local FastEmbed
                                                                              (Phase 5)
    collection.py   the Qdrant collection + payload indexes on the ACL fields (Phase 5)
    indexer.py      chunks -> Qdrant points, incremental, ACL in every payload (Phase 5)
    acl_filter.py   verified user -> Qdrant filter (same rules as can_read)   (Phase 6)
    reranker.py     cross-encoder that re-scores the candidates               (Phase 6)
    search.py       secure hybrid search: filter -> fuse -> double-check -> rerank
                                                                              (Phase 6)

Flow:
    index:   chunks.jsonl -> indexer -> embeddings -> Qdrant "enterprise_docs"
    search:  user + question -> acl_filter + embeddings -> Qdrant (dense + sparse, both
             filtered) -> RRF fusion -> can_read double-check -> reranker -> top 5
"""
