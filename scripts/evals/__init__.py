"""
PACKAGE: scripts.evals - Phase 11 evaluations against the real system.

    corpus.py           loads chunks, personas, attack/injection/question sets, secrets
    metrics.py          recall@k, MRR, number grounding
    retrieval_eval.py   dense vs sparse vs hybrid vs hybrid+rerank
    security_eval.py    RBAC leak suite, direct + indirect prompt injection
    answer_eval.py      golden-answer correctness, citations, grounding, refusals
    report.py           -> reports/EVAL_REPORT.md

Run them all: python -m scripts.run_evals --qdrant-url http://localhost:6333
"""
