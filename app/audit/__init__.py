"""
PACKAGE: app.audit - the paper trail.  (Phase 9)

    models.py    `audit_events` table: append-only, tamper-evident (hash chain)
    service.py   record() events, verify_chain(), masking for viewers, statistics

Recorded: every query and search (who, which documents, flags, timings - NOT the
answer), logins (ok / failed), rate-limit hits, admin actions (incl. blocked self-grants),
and every viewing of the log itself. Read via /admin/audit (api/audit.py).
"""
