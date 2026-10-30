"""
FILE:         scripts/run_evals.py
WHAT IT DOES: Runs every Phase 11 evaluation against the REAL system (Qdrant + local
              models + Ollama) and writes the report.
WHERE IT FITS: Phase 11. Run after ingest + index; needs the Ollama container running.
USED BY:      you.

    python -m scripts.run_evals --qdrant-url http://localhost:6333
    python -m scripts.run_evals --qdrant-url http://localhost:6333 --only injection,answers
        (re-runs just those sections; the others are kept from the previous results)

Sections: retrieval, leak_search, leak_answers, injection, injection_heldout,
          indirect_injection, answers

Outputs:
    reports/EVAL_REPORT.md      human-readable results
    reports/eval_results.json   every number and per-question detail

A full run takes about an hour on a laptop when run on the host (the CPU reranker is the
bottleneck: ~600 searches and ~270 LLM answers).
"""

import argparse
import json
import os
import time
from datetime import UTC, datetime

from app.core.config import PROJECT_ROOT, get_settings

REPORT_DIR = PROJECT_ROOT / "reports"

# Full-pipeline leak attacks are run for these (lowest clearance + the special cases).
LLM_LEAK_PERSONAS = ["u_intern", "u_sales_rep", "u_hr_partner", "u_it_admin"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Phase 11 evaluations.")
    parser.add_argument("--qdrant-url", help="override QDRANT_URL (e.g. Docker Qdrant)")
    parser.add_argument("--only", help="comma-separated sections to re-run (see docstring)")
    args = parser.parse_args()
    if args.qdrant_url:
        os.environ["QDRANT_URL"] = args.qdrant_url
        get_settings.cache_clear()

    from app.auth.personas import load_personas
    from app.core.vectorstore import get_qdrant_client
    from app.generation.llm import get_llm
    from app.retrieval.embeddings import get_embedder
    from app.retrieval.reranker import get_reranker
    from scripts.evals import answer_eval, corpus, report, retrieval_eval, security_eval

    s = get_settings()
    personas, chunks, secrets = load_personas(), corpus.load_chunks(), corpus.load_secrets()
    attacks = corpus.load_attacks()
    emb, rr, client = get_embedder(), get_reranker(), get_qdrant_client()
    llm = get_llm()
    intern = personas["u_intern"]
    started = time.perf_counter()

    # Each section: name -> how to compute it.
    sections = {
        # 1. retrieval quality (no LLM)
        "retrieval": lambda: retrieval_eval.evaluate_retrieval(
            corpus.load_retrieval_questions(), personas["u_ceo"], emb, rr, client,
            s.qdrant_collection),
        # 2. leak suite at search level: every persona x every attack (no LLM)
        "leak_search": lambda: security_eval.leak_search_eval(
            personas, attacks, chunks, secrets, emb, rr),
        # 3. leak suite through the full pipeline (LLM)
        "leak_answers": lambda: security_eval.leak_answer_eval(
            [personas[u] for u in LLM_LEAK_PERSONAS], attacks, chunks, secrets, emb, rr, llm),
        # 4. prompt injection: the tuning set, then the held-out set
        "injection": lambda: security_eval.injection_eval(
            intern, corpus.load_injections(), chunks, secrets, emb, rr, llm),
        "injection_heldout": lambda: security_eval.injection_eval(
            intern, corpus.load_injections("injections_heldout.yaml"), chunks, secrets,
            emb, rr, llm),
        "indirect_injection": lambda: security_eval.indirect_injection_eval(
            intern, emb, rr, llm, client),
        # 5. answer quality
        "answers": lambda: answer_eval.answer_eval(corpus.load_golden(), personas, chunks,
                                                   emb, rr, llm),
    }
    wanted = args.only.split(",") if args.only else list(sections)
    unknown = set(wanted) - set(sections)
    if unknown:
        raise SystemExit(f"unknown sections: {sorted(unknown)}")

    # Keep earlier results for sections not re-run this time.
    results_path = REPORT_DIR / "eval_results.json"
    results: dict = (json.loads(results_path.read_text(encoding="utf-8"))
                     if args.only and results_path.exists() else {})
    runs = results.get("meta", {}).get("section_runs", {})
    for name in wanted:
        # Keep the very first injection result, to report "before -> after hardening".
        if name == "injection" and "injection" in results and "injection_baseline" not in results:
            results["injection_baseline"] = results["injection"]
        print(f"[{time.perf_counter() - started:6.0f}s] {name}", flush=True)
        results[name] = sections[name]()
        runs[name] = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    results["meta"] = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "llm_model": s.llm_model, "embedding_model": s.embedding_model,
        "reranker_model": s.reranker_model, "chunks": len(chunks),
        "documents": len({c.doc_id for c in chunks}),
        "section_runs": runs,  # when each section was last computed
    }

    # --- write outputs (the report needs every section to exist) ---
    REPORT_DIR.mkdir(exist_ok=True)
    results_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    if set(sections) <= set(results):
        (REPORT_DIR / "EVAL_REPORT.md").write_text(report.render(results), encoding="utf-8")
    print(f"[{time.perf_counter() - started:6.0f}s] done -> {REPORT_DIR}", flush=True)


if __name__ == "__main__":
    main()
