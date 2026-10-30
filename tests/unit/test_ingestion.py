"""
FILE:         tests/unit/test_ingestion.py
WHAT IT TESTS: The whole ingestion pipeline (app/ingestion/pipeline.py): outputs, the
              documents registry, fail-closed behaviour, golden facts - and a chunk-level
              leak test: what each persona could retrieve, chunk by chunk.
WHERE IT FITS: Phase 4.

Sections:
    OUTPUTS        report, chunks.jsonl, nothing failed, poison removed
    GOLDEN FACTS   every known answer survives parsing + chunking
    LEAK CHECKS    per persona: readable chunks never contain what they must not see
    REGISTRY       new -> unchanged -> changed; unlisted files never ingested
"""

import json
import re
import shutil

from openpyxl import load_workbook

from app.core.access import can_read
from app.core.database import get_session_factory
from app.ingestion.models import DocumentRecord
from app.ingestion.pipeline import ingest
from scripts.dataset.employees import build_roster


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text)


# =============================================================================
# OUTPUTS
# =============================================================================
def test_every_document_is_ingested(dataset, ingested) -> None:
    _, manifest, _ = dataset
    assert not ingested.failed
    assert {d.doc_id for d in ingested.documents} == {d.doc_id for d in manifest.documents}
    assert all(d.chunks > 0 for d in ingested.documents)


def test_chunks_file_round_trips(dataset, ingested, tmp_path) -> None:
    raw_dir, _, _ = dataset
    ingest(raw_dir / "manifest.yaml", out_dir=tmp_path)
    lines = (tmp_path / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(ingested.chunks)
    first = json.loads(lines[0])
    assert {"chunk_id", "text", "clearance_level", "departments"} <= first.keys()


def test_poison_never_reaches_a_chunk(ingested) -> None:
    assert not any("SYSTEM OVERRIDE" in c.text for c in ingested.chunks)
    wifi = next(d for d in ingested.documents if d.doc_id == "office-wifi-guide")
    assert wifi.hidden_removed and "SYSTEM OVERRIDE" in wifi.hidden_removed[0]


# =============================================================================
# GOLDEN FACTS - the answer key must be findable in the chunks
# =============================================================================
def test_golden_answers_survive_ingestion(dataset, ingested) -> None:
    _, _, golden = dataset
    for q in golden:
        text = _norm(" ".join(c.text for c in ingested.chunks if c.doc_id == q.doc_id))
        for evidence in q.evidence:
            assert evidence in text, f"{q.id}: {evidence!r} lost in ingestion"


# =============================================================================
# LEAK CHECKS - simulate "retrieve everything I'm allowed to" for each persona
# =============================================================================
def _readable_text(ingested, persona) -> str:
    return " ".join(c.text for c in ingested.chunks if can_read(persona, c))


# Chunks never LOOSEN access: if you can read a chunk, you can read its document.
def test_chunks_are_never_looser_than_their_document(dataset, ingested, personas) -> None:
    _, manifest, _ = dataset
    for persona in personas.values():
        for c in ingested.chunks:
            if can_read(persona, c):
                assert can_read(persona, manifest.get(c.doc_id)), (persona.user_id, c.chunk_id)


# Salaries in the directory: only HR, Finance, CFO, CEO can ever retrieve them.
def test_directory_salaries_only_reach_hr_and_finance(ingested, personas) -> None:
    lena = next(e for e in build_roster() if e.name == "Lena Okafor")
    salary_line = f"Name: Lena Okafor | Base Salary (USD): {lena.base_salary}"
    allowed = {"u_hr_partner", "u_finance_analyst", "u_cfo", "u_ceo"}
    for uid, persona in personas.items():
        assert (salary_line in _readable_text(ingested, persona)) == (uid in allowed), uid


# Performance ratings: HR only (plus the CEO, who is in every department).
def test_ratings_only_reach_hr(ingested, personas) -> None:
    for uid, persona in personas.items():
        sees = "Performance Rating (2025)" in _readable_text(ingested, persona)
        assert sees == (uid in {"u_hr_partner", "u_ceo"}), uid


# Executive pay and the layoff plan: executives only.
def test_restricted_facts_only_reach_executives(ingested, personas) -> None:
    for uid, persona in personas.items():
        text = _readable_text(ingested, persona)
        is_exec = uid in {"u_cfo", "u_ceo"}
        assert ("$310,000" in text) == is_exec, uid
        assert ("6 positions will be eliminated" in text) == is_exec, uid


# The intern only ever sees public material.
def test_intern_sees_only_public_chunks(ingested, personas) -> None:
    readable = [c for c in ingested.chunks if can_read(personas["u_intern"], c)]
    assert readable and all(c.classification == "public" for c in readable)


# =============================================================================
# REGISTRY - change detection and fail-closed behaviour
# =============================================================================
def test_registry_tracks_new_unchanged_and_changed(client, dataset, tmp_path) -> None:
    raw_dir, _, _ = dataset
    copy = tmp_path / "raw"
    shutil.copytree(raw_dir, copy)
    manifest_path = copy / "manifest.yaml"

    with get_session_factory()() as db:
        first = ingest(manifest_path, out_dir=tmp_path / "out", db=db)
        second = ingest(manifest_path, out_dir=tmp_path / "out", db=db)

        # Edit one spreadsheet cell -> only that document becomes "changed".
        path = copy / "public" / "holiday_calendar_2026.xlsx"
        wb = load_workbook(path)
        wb.active["C2"] = "New Year's Day (edited)"
        wb.save(path)
        third = ingest(manifest_path, out_dir=tmp_path / "out", db=db)

        record = db.get(DocumentRecord, "workplace-investigation-2026-07")

    assert {d.status for d in first.documents} == {"new"}
    assert {d.status for d in second.documents} == {"unchanged"}
    changed = {d.doc_id for d in third.documents if d.status == "changed"}
    assert changed == {"holiday-calendar-2026"}
    assert record.denied_users == ["u_hr_partner"] and record.chunk_count > 0


# A file dropped into the folder without a manifest entry is NEVER ingested.
def test_unlisted_files_are_not_ingested(dataset, tmp_path) -> None:
    raw_dir, _, _ = dataset
    copy = tmp_path / "raw"
    shutil.copytree(raw_dir, copy)
    shutil.copy(copy / "executive" / "board_minutes_2026_q3.pdf", copy / "public" / "leaked.pdf")

    report = ingest(copy / "manifest.yaml", out_dir=tmp_path / "out")
    assert report.unlisted_files == ["public/leaked.pdf"]
    assert not any(c.source_path == "public/leaked.pdf" for c in report.chunks)
