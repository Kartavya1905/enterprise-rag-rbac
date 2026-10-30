"""
PACKAGE: app.security - defences around the LLM.  (Phase 7)

    injection.py      spots prompt-injection attempts (used on questions AND on chunks)
    redaction.py      masks tax IDs, SSNs, bank accounts, card numbers
    output_guard.py   checks the answer: canary leak, redaction, citations, grounding

Layering (each layer assumes the previous ones can fail):
    1. search (Phase 6)  - restricted chunks never reach the model at all
    2. input guard       - injected questions are refused before searching
    3. context guard     - poisoned chunks are dropped; sensitive ids masked
    4. prompt rules      - sources are fenced DATA; the model is told to ignore orders
    5. output guard      - leaks of the rules, sensitive ids, fake citations removed
"""
