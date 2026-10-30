"""
FILE:         tests/unit/test_dataset.py
WHAT IT TESTS: The synthetic dataset (Phase 2): it is consistent, covers every access
              case, and the facts in the answer key really are inside the documents.
WHERE IT FITS: Phase 2. Uses the `dataset` fixture (tests/conftest.py), which generates a
              FRESH copy in a temporary folder - so it tests the generator itself, not
              whatever happens to be in data/.

Sections:
    SETUP          text-extraction helpers
    COVERAGE       every clearance level, file type and trap is present
    INTEGRITY      references, columns, poison payload, salary numbers
    ACCESS         specific "should X read Y?" expectations

(Golden Q&A answers are checked against the INGESTED chunks in test_ingestion.py.)
"""

import re
from pathlib import Path

import pytest
from openpyxl import load_workbook
from pypdf import PdfReader

from app.core.access import Clearance, can_read
from scripts.dataset.content import INJECTION_PAYLOAD
from scripts.dataset.employees import SALARY_BANDS, build_roster

# =============================================================================
# SETUP
# =============================================================================


# A deliberately NAIVE text extraction (pypdf) - what a careless RAG pipeline would do.
# Used to prove the hidden injection really is extractable from the poisoned PDF.
def naive_pdf_text(path: Path) -> str:
    text = " ".join(page.extract_text() for page in PdfReader(path).pages)
    return re.sub(r"\s+", " ", text)


# The column names of a spreadsheet's first sheet.
def xlsx_header(path: Path) -> list[str]:
    ws = load_workbook(path, read_only=True).worksheets[0]
    return [c for c in next(ws.iter_rows(max_row=1, values_only=True))]


# =============================================================================
# COVERAGE - the dataset exercises everything later phases need to test
# =============================================================================
def test_every_clearance_level_is_represented(dataset) -> None:
    _, manifest, _ = dataset
    assert {d.clearance_level for d in manifest.documents} == set(Clearance)


def test_every_source_type_is_represented(dataset) -> None:
    _, manifest, _ = dataset
    assert {d.source_type for d in manifest.documents} == {"pdf", "docx", "xlsx"}


# Named grant, named block, column rule and poisoned doc all exist.
def test_special_access_cases_exist(dataset) -> None:
    _, manifest, _ = dataset
    docs = manifest.documents
    assert any(d.allowed_users for d in docs)
    assert any(d.denied_users for d in docs)
    assert any(d.column_policies for d in docs)
    assert any("poisoned" in d.tags for d in docs)


# =============================================================================
# INTEGRITY - the pieces agree with each other
# =============================================================================
# Every user named in a grant/block is one of the 8 personas (no typos).
def test_acl_user_references_are_known_personas(dataset, personas) -> None:
    _, manifest, _ = dataset
    for doc in manifest.documents:
        assert set(doc.allowed_users + doc.denied_users) <= personas.keys(), doc.doc_id


# Column rules point at columns that really exist in the spreadsheet.
def test_column_policies_name_real_columns(dataset) -> None:
    raw_dir, manifest, _ = dataset
    for doc in manifest.documents:
        if doc.column_policies:
            header = xlsx_header(raw_dir / doc.path)
            for policy in doc.column_policies:
                assert set(policy.columns) <= set(header), doc.doc_id


# The hidden injection is (a) in a PUBLIC doc and (b) extractable by a parser.
def test_poisoned_doc_carries_extractable_injection(dataset) -> None:
    raw_dir, manifest, _ = dataset
    poisoned = [d for d in manifest.documents if "poisoned" in d.tags]
    assert poisoned
    for doc in poisoned:
        assert doc.clearance_level == Clearance.PUBLIC  # reachable by every user
        assert INJECTION_PAYLOAD[:40] in naive_pdf_text(raw_dir / doc.path)


# Every document has at least one golden question, and none points at a missing doc.
def test_golden_questions_cover_every_document(dataset) -> None:
    _, manifest, golden = dataset
    assert {q.doc_id for q in golden} == {d.doc_id for d in manifest.documents}


# Personas are real employees; IDs are unique; salaries sit inside their band.
def test_roster_is_consistent_with_salary_bands_and_personas(personas) -> None:
    roster = build_roster()
    names = {e.name for e in roster}
    assert {p.name for p in personas.values()} <= names
    # A persona's login email is the same address the employee directory lists.
    email_by_name = {e.name: e.email for e in roster}
    for p in personas.values():
        assert p.email == email_by_name[p.name], p.user_id
    assert len({e.employee_id for e in roster}) == len(roster)
    for e in roster:
        if e.is_executive:
            assert e.base_salary is None
        else:
            lo, hi = SALARY_BANDS[e.level]
            assert lo <= e.base_salary <= hi, e.name


# Payroll has no executives, and its salaries match the employee directory.
def test_payroll_excludes_executives_and_matches_directory(dataset) -> None:
    raw_dir, manifest, _ = dataset
    payroll = load_workbook(raw_dir / manifest.get("payroll-2026-q3").path, read_only=True)
    directory = load_workbook(raw_dir / manifest.get("employee-directory").path, read_only=True)
    salary_by_id = {r[0]: r[8] for r in directory.worksheets[0].iter_rows(min_row=2,
                                                                          values_only=True)}
    payroll_rows = list(payroll.worksheets[0].iter_rows(min_row=2, values_only=True))
    assert payroll_rows
    for row in payroll_rows:
        assert row[3] != "EXEC"
        assert row[4] == salary_by_id[row[0]]


# =============================================================================
# ACCESS - concrete "should this person read this document?" checks
# =============================================================================
@pytest.mark.parametrize(
    ("user_id", "doc_id", "expected"),
    [
        ("u_intern", "employee-handbook", True),
        ("u_intern", "product-roadmap-2027", False),
        ("u_intern", "payroll-2026-q3", False),
        ("u_engineer", "platform-architecture", True),
        ("u_sales_rep", "platform-architecture", False),
        ("u_eng_manager", "cloud-cost-review-fy2027", True),   # allowed_users grant
        ("u_eng_manager", "department-budgets-fy2027", False),
        ("u_hr_partner", "payroll-2026-q3", True),
        ("u_hr_partner", "workplace-investigation-2026-07", False),  # denied_users
        ("u_finance_analyst", "exec-compensation-2026", False),
        ("u_cfo", "board-minutes-2026-q3", True),
        ("u_cfo", "platform-architecture", False),  # high clearance, wrong department
        ("u_ceo", "restructuring-plan-2027", True),
    ],
)
def test_access_expectations(dataset, personas, user_id, doc_id, expected) -> None:
    _, manifest, _ = dataset
    assert can_read(personas[user_id], manifest.get(doc_id)) is expected


# The CEO belongs to every department with top clearance -> reads all 18 docs.
def test_ceo_can_read_everything(dataset, personas) -> None:
    _, manifest, _ = dataset
    assert all(can_read(personas["u_ceo"], d) for d in manifest.documents)
