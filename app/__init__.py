"""
PACKAGE:      app
WHAT IT IS:   The Enterprise RAG assistant with role-based access control.

    api/          HTTP routes - the "front door"            (Phase 1 health; more in Phase 8)
    auth/         who you are: users, roles, clearance      (Phase 3)
    ingestion/    reading documents, chunking, ACL labels   (Phase 4)
    retrieval/    access-filtered hybrid search             (Phases 5-6)
    security/     prompt-injection and leak protection      (Phase 7)
    generation/   prompts and the LLM client                (Phase 7)
    audit/        logging who asked what                    (Phase 9)
    core/         shared plumbing: settings, DB, Qdrant, access rules
"""

__version__ = "0.1.0"
