"""
FILE:         tests/unit/test_indexer.py
WHAT IT TESTS: Loading chunks into Qdrant (app/retrieval/indexer.py + collection.py):
              every point carries its ACL, re-runs are incremental, and - critically -
              an ACL change with an UNCHANGED file still reaches the index.
WHERE IT FITS: Phase 5. Uses in-memory Qdrant and the offline HashingEmbedder
              (tests/fakes.py); one test at the end uses the real FastEmbed models.

Sections:
    BASICS         points, payload ACL, vectors
    INCREMENTAL    unchanged / content change / ACL change / removed document
    SAFETY         empty input refused, model-size mismatch refused
    REAL MODEL     semantic search sanity check with the actual embedding model
"""

import shutil

import pytest
import yaml
from openpyxl import load_workbook
from qdrant_client import models

from app.core.config import get_settings
from app.core.vectorstore import get_qdrant_client
from app.ingestion.pipeline import ingest
from app.retrieval.collection import DENSE, SPARSE, CollectionMismatch, ensure_collection
from app.retrieval.indexer import index_chunks
from tests.fakes import HashingEmbedder

FAKE = HashingEmbedder()


def _collection() -> str:
    return get_settings().qdrant_collection


def _points_for(doc_id: str) -> list:
    points, _ = get_qdrant_client().scroll(
        _collection(),
        scroll_filter=models.Filter(must=[
            models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))]),
        limit=1000, with_payload=True,
    )
    return points


# A private, editable copy of the dataset (for tests that change files or the manifest).
@pytest.fixture
def raw_copy(dataset, tmp_path):
    copy = tmp_path / "raw"
    shutil.copytree(dataset[0], copy)
    return copy


def _ingest(raw_dir, tmp_path):
    return ingest(raw_dir / "manifest.yaml", out_dir=tmp_path / "out").chunks


# =============================================================================
# BASICS
# =============================================================================
def test_every_chunk_becomes_a_point_with_its_acl(test_env, ingested) -> None:
    report = index_chunks(ingested.chunks, embedder=FAKE)
    assert report.total_points == len(ingested.chunks)
    assert {d.status for d in report.documents} == {"indexed"}

    client = get_qdrant_client()
    by_id = {c.chunk_id: c for c in ingested.chunks}
    points = client.retrieve(_collection(), ids=list(by_id), with_payload=True,
                             with_vectors=True)
    assert len(points) == len(by_id)
    for p in points:
        chunk = by_id[str(p.id)]
        # The ACL in Qdrant is exactly the chunk's ACL.
        assert p.payload["clearance_level"] == chunk.clearance_level
        assert p.payload["departments"] == [str(d) for d in chunk.departments]
        assert p.payload["allowed_users"] == chunk.allowed_users
        assert p.payload["denied_users"] == chunk.denied_users
        assert p.payload["text"] == chunk.text
        assert len(p.vector[DENSE]) == FAKE.dense_dim
        assert p.vector[SPARSE].indices  # keyword vector present


# =============================================================================
# INCREMENTAL
# =============================================================================
def test_second_run_changes_nothing(test_env, ingested) -> None:
    index_chunks(ingested.chunks, embedder=FAKE)
    again = index_chunks(ingested.chunks, embedder=FAKE)
    assert {d.status for d in again.documents} == {"unchanged"}
    assert again.total_points == len(ingested.chunks)


# A changed file -> only that document is re-indexed, and no stale points remain.
def test_content_change_reindexes_only_that_document(test_env, raw_copy, tmp_path) -> None:
    index_chunks(_ingest(raw_copy, tmp_path), embedder=FAKE)

    path = raw_copy / "public" / "holiday_calendar_2026.xlsx"
    wb = load_workbook(path)
    wb.active["C2"] = "New Year's Day (edited)"
    wb.save(path)
    chunks = _ingest(raw_copy, tmp_path)
    report = index_chunks(chunks, embedder=FAKE)

    reindexed = {d.doc_id for d in report.documents if d.status == "indexed"}
    assert reindexed == {"holiday-calendar-2026"}
    holiday = _points_for("holiday-calendar-2026")
    assert len(holiday) == sum(c.doc_id == "holiday-calendar-2026" for c in chunks)
    assert all("(edited)" in p.payload["text"] for p in holiday)


# SECURITY: tighten a document's ACL in the manifest WITHOUT touching the file.
# The index must pick up the new label (a file-hash-only check would miss this).
def test_acl_change_with_same_file_reaches_the_index(test_env, raw_copy, tmp_path) -> None:
    index_chunks(_ingest(raw_copy, tmp_path), embedder=FAKE)
    assert all(p.payload["departments"] == ["all"] for p in _points_for("product-roadmap-2027"))

    manifest_path = raw_copy / "manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    roadmap = next(d for d in manifest["documents"] if d["doc_id"] == "product-roadmap-2027")
    roadmap["departments"] = ["engineering"]
    roadmap["clearance_level"] = 3
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    report = index_chunks(_ingest(raw_copy, tmp_path), embedder=FAKE)
    reindexed = {d.doc_id for d in report.documents if d.status == "indexed"}
    assert reindexed == {"product-roadmap-2027"}
    for p in _points_for("product-roadmap-2027"):
        assert p.payload["departments"] == ["engineering"]
        assert p.payload["clearance_level"] == 3


# A document that is no longer ingested disappears from the index.
def test_removed_document_is_deleted_from_index(test_env, ingested) -> None:
    index_chunks(ingested.chunks, embedder=FAKE)
    remaining = [c for c in ingested.chunks if c.doc_id != "restructuring-plan-2027"]
    report = index_chunks(remaining, embedder=FAKE)
    assert report.removed_docs == ["restructuring-plan-2027"]
    assert _points_for("restructuring-plan-2027") == []
    assert report.total_points == len(remaining)


# =============================================================================
# SAFETY
# =============================================================================
def test_empty_chunk_set_is_refused(test_env, ingested) -> None:
    index_chunks(ingested.chunks, embedder=FAKE)
    with pytest.raises(ValueError, match="empty"):
        index_chunks([], embedder=FAKE)
    assert get_qdrant_client().count(_collection()).count == len(ingested.chunks)


def test_embedding_size_mismatch_is_refused(test_env) -> None:
    client = get_qdrant_client()
    ensure_collection(client, "c", dense_dim=64)
    with pytest.raises(CollectionMismatch):
        ensure_collection(client, "c", dense_dim=384)
    assert ensure_collection(client, "c", dense_dim=384, recreate=True) is True


# =============================================================================
# REAL MODEL - does semantic search find the right chunk? (no ACL filter yet: Phase 6)
# =============================================================================
@pytest.fixture(scope="session")
def real_embedder():
    from app.retrieval.embeddings import FastEmbedEmbedder

    s = get_settings()
    try:
        return FastEmbedEmbedder(s.embedding_model, s.sparse_model, s.model_cache_dir)
    except Exception as exc:  # noqa: BLE001 - offline and models not cached yet
        pytest.skip(f"embedding models unavailable: {exc}")


@pytest.mark.parametrize(
    ("question", "doc_id", "section"),
    [
        ("How many vacation days do I get?", "employee-handbook", "1. Time Off"),
        ("Which app do I need for remote network access?", "it-helpdesk-faq", None),
        ("How fast must we respond to a critical outage?", "incident-runbook", None),
    ],
)
def test_semantic_search_finds_the_right_chunk(
    test_env, ingested, real_embedder, question, doc_id, section
) -> None:
    public_and_internal = [c for c in ingested.chunks if c.clearance_level <= 2]
    index_chunks(public_and_internal, embedder=real_embedder)
    q = real_embedder.embed_query(question)
    hits = get_qdrant_client().query_points(
        _collection(), query=q.dense, using=DENSE, limit=3, with_payload=True
    ).points
    assert hits[0].payload["doc_id"] == doc_id
    if section:
        assert hits[0].payload["section"] == section
