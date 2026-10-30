"""
FILE:         tests/evals/test_metrics.py
WHAT IT TESTS: The evaluation building blocks (scripts/evals/metrics.py + corpus.py), so
              the numbers in reports/EVAL_REPORT.md can be trusted.
WHERE IT FITS: Phase 11.
"""

import base64

from scripts.evals.answer_eval import is_correct
from scripts.evals.corpus import (
    Question,
    can_answer,
    load_injections,
    load_retrieval_questions,
)
from scripts.evals.metrics import numbers_grounded, recall_at_k, reciprocal_rank


# =============================================================================
# RETRIEVAL METRICS
# =============================================================================
def test_recall_at_k() -> None:
    ranked = ["a", "b", "c"]
    assert recall_at_k(ranked, "a", 1) == 1.0
    assert recall_at_k(ranked, "c", 1) == 0.0
    assert recall_at_k(ranked, "c", 5) == 1.0


def test_reciprocal_rank() -> None:
    assert reciprocal_rank(["a", "b", "c"], "a") == 1.0
    assert reciprocal_rank(["a", "b", "c"], "b") == 0.5
    assert reciprocal_rank(["a", "b", "c"], "z") == 0.0


# =============================================================================
# ANSWER METRICS
# =============================================================================
def test_numbers_grounded() -> None:
    ctx = ["Total executive base salary: $1,090,000. CEO base salary $310,000."]
    assert numbers_grounded("The CEO earns $310,000 [S1].", ctx)
    assert not numbers_grounded("The CEO earns $350,000 [S1].", ctx)  # invented number
    assert numbers_grounded("No numbers here [S1].", ctx)  # [S1] is not a number


def test_is_correct_is_lenient_on_wording_strict_on_facts() -> None:
    q = Question("How many positions?", "restructuring-plan-2027",
                 "6 positions (4 Sales, 2 Engineering QA)", ("6 positions will be eliminated",))
    assert is_correct(q, "It eliminates 6 positions: 4 in Sales and 2 in Engineering (QA).")
    assert not is_correct(q, "It eliminates 5 positions.")


# =============================================================================
# CORPUS
# =============================================================================
def test_column_level_answerability(ingested, personas) -> None:
    # Directory is open to staff, but its SALARY column is not: the engineer cannot
    # answer a salary question even though they can read the directory.
    salary_q = next(q for q in load_retrieval_questions() if q.evidence
                    and "salary" in q.question.lower() and q.doc_id == "employee-directory")
    assert not can_answer(personas["u_engineer"], salary_q, ingested.chunks)
    assert can_answer(personas["u_hr_partner"], salary_q, ingested.chunks)


def test_injection_disguises_are_applied() -> None:
    injections = load_injections()
    b64 = next(i.text for i in injections if "base64" in i.text)
    assert "PWNED" in base64.b64decode(b64.rsplit(" ", 1)[-1]).decode()  # decodes back
    assert any("​" in i.text for i in injections)  # zero-width variant exists


def test_secrets_the_user_typed_are_not_leaks() -> None:
    from scripts.evals.corpus import leaked

    forbidden = {"Lumen Analytics", "310,000"}
    answer = "I couldn't find anything about Lumen Analytics."
    assert leaked(answer, forbidden, asked="Tell me about Lumen Analytics") == set()
    assert leaked("The CEO earns 310,000", forbidden, asked="CEO pay?") == {"310,000"}
