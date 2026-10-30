"""
FILE:         tests/unit/test_chunker.py
WHAT IT TESTS: The chunker (app/ingestion/chunker.py): size limits, context headers,
              stable ids, section paths, and - most importantly - that every chunk carries
              the right access label.
WHERE IT FITS: Phase 4.
"""

from datetime import UTC, datetime

from app.core.access import Department
from app.ingestion.chunker import MAX_TOKENS, chunk_document, estimate_tokens
from app.ingestion.elements import Heading, Paragraph, ParsedDocument
from app.ingestion.manifest import DocumentEntry

NOW = datetime(2026, 10, 29, tzinfo=UTC)


def _body(chunk) -> str:
    return chunk.text.split("\n", 1)[1]  # strip the "[Document: ...]" header line


def _entry(**overrides) -> DocumentEntry:
    base = dict(doc_id="test-doc", path="x/test.pdf", title="Test Doc", source_type="pdf",
                owner="me", clearance_level=2, departments=["engineering"])
    return DocumentEntry(**(base | overrides))


# =============================================================================
# SHAPE OF EVERY CHUNK
# =============================================================================
def test_every_chunk_has_a_context_header_and_fits(ingested) -> None:
    for c in ingested.chunks:
        assert c.text.startswith(f"[Document: {c.doc_title}")
        assert estimate_tokens(_body(c)) <= MAX_TOKENS, c.chunk_id


def test_chunk_ids_are_unique_and_deterministic(dataset, ingested) -> None:
    ids = [c.chunk_id for c in ingested.chunks]
    assert len(ids) == len(set(ids))
    # Re-chunking the same document version gives the same ids (idempotent indexing).
    from app.ingestion.parsers import parse_document

    raw_dir, manifest, _ = dataset
    entry = manifest.get("employee-handbook")
    first = [c for c in ingested.chunks if c.doc_id == entry.doc_id]
    parsed = parse_document(raw_dir / entry.path, entry.source_type)
    again = chunk_document(entry, parsed, first[0].doc_sha256, NOW)
    assert [c.chunk_id for c in again] == [c.chunk_id for c in first]


# =============================================================================
# STRUCTURE
# =============================================================================
# Sections become part of the chunk; a new heading always starts a new chunk.
def test_sections_split_chunks(ingested) -> None:
    handbook = [c for c in ingested.chunks if c.doc_id == "employee-handbook"]
    sections = [c.section for c in handbook]
    assert "1. Time Off" in sections and "3. Expenses" in sections
    expenses = next(c for c in handbook if c.section == "3. Expenses")
    assert "Section: 3. Expenses" in expenses.text
    assert "$25" in expenses.text and "20 days" not in expenses.text


# A very long section is split into several chunks, each within the limit.
def test_long_paragraphs_are_split() -> None:
    sentence = "The fleet API must stay available during every planned maintenance window. "
    parsed = ParsedDocument([Heading("Reliability", 1), Paragraph(sentence * 120)])
    chunks = chunk_document(_entry(), parsed, "sha", NOW)
    assert len(chunks) > 3
    assert all(c.section == "Reliability" for c in chunks)
    assert all(estimate_tokens(_body(c)) <= MAX_TOKENS for c in chunks)


# =============================================================================
# ACCESS LABELS ON CHUNKS - the security core of Phase 4
# =============================================================================
# Prose chunks carry EXACTLY their document's label.
def test_prose_chunks_inherit_the_document_label(dataset, ingested) -> None:
    _, manifest, _ = dataset
    for c in ingested.chunks:
        if c.source_type == "xlsx":
            continue
        doc = manifest.get(c.doc_id)
        assert (c.clearance_level, c.departments, c.allowed_users, c.denied_users) == (
            doc.clearance_level, doc.departments, doc.allowed_users, doc.denied_users)


# The mixed-sensitivity directory is split by column label.
def test_directory_columns_are_separated_by_label(ingested) -> None:
    directory = [c for c in ingested.chunks if c.doc_id == "employee-directory"]
    base = [c for c in directory if "Base Salary (USD)" not in c.columns
            and "Performance Rating (2025)" not in c.columns]
    salary = [c for c in directory if "Base Salary (USD)" in c.columns]
    rating = [c for c in directory if "Performance Rating (2025)" in c.columns]
    assert base and salary and rating

    for c in base:  # everyone-at-clearance-2 chunks never mention pay or ratings
        assert c.clearance_level == 2 and c.departments == [Department.ALL]
        assert "Base Salary" not in c.text and "Performance Rating" not in c.text
    for c in salary:  # salary: HR + Finance only, and says whose salary it is
        assert c.clearance_level == 3
        assert set(c.departments) == {Department.HR, Department.FINANCE}
        assert "Name: " in c.text and "Title:" not in c.text
    for c in rating:  # ratings: HR only
        assert c.departments == [Department.HR]
