"""
PACKAGE: app.api - HTTP routes (the "front door").

    health.py   GET /health, GET /health/ready          (Phase 1)
    auth.py     POST /auth/login, GET /auth/me          (Phase 3)
    search.py   POST /search - access-filtered chunks   (Phase 6)
    query.py    POST /query  - cited LLM answers         (Phase 7)
    admin.py    /admin/* - documents + ACL management   (Phase 8)
    audit.py    /admin/audit* - read the audit log       (Phase 9)
"""
