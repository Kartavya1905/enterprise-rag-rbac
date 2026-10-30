"""
FILE:         tests/unit/test_admin_api.py
WHAT IT TESTS: Document administration over HTTP (app/api/admin.py + app/ingestion/admin.py):
              only admins get in, ACL changes take effect in search immediately, admins
              cannot grant themselves access, uploads are validated, removal works.
WHERE IT FITS: Phase 8. Runs on a private copy of the dataset with offline fakes.

Sections:
    WHO MAY USE /admin      401 / 403 / 200
    CHANGING ACCESS         ACL update -> search results change at once
    SELF-GRANT              an admin cannot open a document to themselves
    UPLOADS                 new document searchable by the right people only; bad files
    REMOVAL                 removed document disappears from search
"""

import shutil
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from fpdf import FPDF

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.ingestion.admin import rebuild
from app.retrieval.embeddings import get_embedder
from app.retrieval.reranker import get_reranker
from tests.fakes import HashingEmbedder, OverlapReranker

EMB = HashingEmbedder()


@pytest.fixture
def admin_api(client: TestClient, login, dataset, tmp_path, monkeypatch):
    # A private, editable copy of the documents for this test.
    raw = tmp_path / "raw"
    shutil.copytree(dataset[0], raw)
    monkeypatch.setenv("DOCUMENTS_DIR", str(raw))
    monkeypatch.setenv("PROCESSED_DIR", str(tmp_path / "processed"))
    get_settings.cache_clear()
    with get_session_factory()() as db:
        rebuild(db, EMB)  # ingest + index the copy

    overrides = client.app.dependency_overrides
    overrides[get_embedder] = lambda: EMB
    overrides[get_reranker] = lambda: OverlapReranker()
    yield client, login, raw
    overrides.clear()


def _found(client, headers, query, doc_title) -> bool:
    results = client.post("/search", json={"query": query, "top_k": 10},
                          headers=headers).json()["results"]
    return any(r["doc_title"] == doc_title for r in results)


def _pdf_bytes(text: str) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 6, text)
    return bytes(pdf.output())


# =============================================================================
# WHO MAY USE /admin
# =============================================================================
@pytest.mark.parametrize("user_id", ["u_intern", "u_hr_partner", "u_cfo", "u_ceo"])
def test_non_admins_are_forbidden(admin_api, user_id) -> None:
    client, login, _ = admin_api
    headers = login(user_id)  # even the CEO: reading rights != admin rights
    assert client.get("/admin/documents", headers=headers).status_code == 403
    assert client.patch("/admin/documents/employee-handbook/acl",
                        json={"clearance_level": 4}, headers=headers).status_code == 403


def test_anonymous_is_unauthorized(admin_api) -> None:
    client, _, _ = admin_api
    assert client.get("/admin/documents").status_code == 401


def test_admin_lists_documents_with_labels(admin_api) -> None:
    client, login, _ = admin_api
    docs = client.get("/admin/documents", headers=login("u_it_admin")).json()
    assert len(docs) == 18
    inv = next(d for d in docs if d["doc_id"] == "workplace-investigation-2026-07")
    assert inv["denied_users"] == ["u_hr_partner"] and inv["chunk_count"] > 0


# =============================================================================
# CHANGING ACCESS
# =============================================================================
def test_acl_change_takes_effect_in_search_immediately(admin_api) -> None:
    client, login, raw = admin_api
    sales, eng_mgr = login("u_sales_rep"), login("u_eng_manager")
    q, title = "Product Roadmap 2027 Orbitra Fleet flagship release", "Product Roadmap 2027"
    assert _found(client, sales, q, title)  # roadmap starts open to all staff

    resp = client.patch("/admin/documents/product-roadmap-2027/acl",
                        json={"clearance_level": 3, "departments": ["engineering"]},
                        headers=login("u_it_admin"))
    assert resp.status_code == 200
    assert resp.json()["departments"] == ["engineering"]

    assert not _found(client, sales, q, title)  # sales rep lost access at once
    assert _found(client, eng_mgr, q, title)  # engineering manager still has it
    manifest = yaml.safe_load((raw / "manifest.yaml").read_text(encoding="utf-8"))
    entry = next(d for d in manifest["documents"] if d["doc_id"] == "product-roadmap-2027")
    assert entry["clearance_level"] == 3  # the source of truth was updated too


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"clearance_level": 9}, 422),  # out of range
        ({"departments": ["marketing"]}, 422),  # department that doesn't exist
        ({"departments": []}, 422),  # no department at all
        ({"owner": "me"}, 422),  # not an ACL field
        ({}, 422),  # nothing to change
    ],
)
def test_invalid_acl_changes_are_rejected(admin_api, body, status) -> None:
    client, login, _ = admin_api
    resp = client.patch("/admin/documents/employee-handbook/acl", json=body,
                        headers=login("u_it_admin"))
    assert resp.status_code == status


def test_unknown_document_is_404(admin_api) -> None:
    client, login, _ = admin_api
    resp = client.patch("/admin/documents/no-such-doc/acl", json={"clearance_level": 2},
                        headers=login("u_it_admin"))
    assert resp.status_code == 404


# =============================================================================
# SELF-GRANT - admins manage labels but cannot open documents to themselves
# =============================================================================
def test_admin_cannot_grant_themselves_access(admin_api) -> None:
    client, login, _ = admin_api
    admin = login("u_it_admin")
    q, title = "FY2027 cloud budget savings target", "Cloud Cost Review FY2027"
    assert not _found(client, admin, q, title)  # finance doc: admin can't read it

    resp = client.patch("/admin/documents/cloud-cost-review-fy2027/acl",
                        json={"allowed_users": ["u_eng_manager", "u_it_admin"]}, headers=admin)
    assert resp.status_code == 403
    assert not _found(client, admin, q, title)

    # Changing it for SOMEONE ELSE is fine (HR partner: clearance 3, other department).
    resp = client.patch("/admin/documents/cloud-cost-review-fy2027/acl",
                        json={"allowed_users": ["u_eng_manager", "u_hr_partner"]},
                        headers=admin)
    assert resp.status_code == 200
    assert _found(client, login("u_hr_partner"), q, title)


# A named grant never bypasses clearance: granting a clearance-2 user a clearance-3
# document is accepted as a label, but the user still cannot read it.
def test_named_grant_does_not_bypass_clearance(admin_api) -> None:
    client, login, _ = admin_api
    resp = client.patch("/admin/documents/cloud-cost-review-fy2027/acl",
                        json={"allowed_users": ["u_engineer"]}, headers=login("u_it_admin"))
    assert resp.status_code == 200
    assert not _found(client, login("u_engineer"), "FY2027 cloud budget savings target",
                      "Cloud Cost Review FY2027")


# =============================================================================
# UPLOADS
# =============================================================================
def _upload(client, headers, *, doc_id="hr-relocation-policy", filename="policy.pdf",
            content=None, clearance="3", departments="hr"):
    content = content if content is not None else _pdf_bytes(
        "Relocation Policy 2027. Employees relocating to Toronto receive a relocation "
        "allowance of 12,000 dollars, paid with the first salary.")
    return client.post(
        "/admin/documents", headers=headers,
        files={"file": (filename, content, "application/octet-stream")},
        data={"doc_id": doc_id, "title": "Relocation Policy 2027",
              "clearance_level": clearance, "departments": departments},
    )


def test_uploaded_document_is_searchable_by_the_right_people(admin_api) -> None:
    client, login, raw = admin_api
    resp = _upload(client, login("u_it_admin"))
    assert resp.status_code == 201, resp.text
    assert resp.json()["chunk_count"] >= 1
    assert (raw / "uploads" / "hr-relocation-policy.pdf").is_file()

    q, title = "relocation allowance Toronto", "Relocation Policy 2027"
    assert _found(client, login("u_hr_partner"), q, title)  # HR can read it
    assert not _found(client, login("u_engineer"), q, title)  # engineering cannot
    assert not _found(client, login("u_it_admin"), q, title)  # nor can the uploader


@pytest.mark.parametrize(
    ("kwargs", "status"),
    [
        ({"filename": "evil.exe"}, 422),  # extension not allowed
        ({"content": b"MZ\x90\x00 not really a pdf"}, 422),  # .pdf name, wrong content
        ({"doc_id": "../../etc/passwd"}, 422),  # path traversal attempt
        ({"doc_id": "employee-handbook"}, 409),  # already exists
        ({"departments": "marketing"}, 422),  # unknown department
    ],
)
def test_bad_uploads_are_rejected(admin_api, kwargs, status) -> None:
    client, login, raw = admin_api
    resp = _upload(client, login("u_it_admin"), **kwargs)
    assert resp.status_code == status, resp.text
    assert not any(Path(raw, "uploads").glob("*")) if (raw / "uploads").exists() else True


def test_oversized_upload_is_rejected(admin_api, monkeypatch) -> None:
    client, login, _ = admin_api
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    get_settings.cache_clear()
    big = b"%PDF-" + b"0" * (1024 * 1024 + 10)
    assert _upload(client, login("u_it_admin"), content=big).status_code == 413


# =============================================================================
# REMOVAL
# =============================================================================
def test_removed_document_disappears_from_search(admin_api) -> None:
    client, login, raw = admin_api
    q, title = "Which wifi network ORB-CORP employees", "Office Wi-Fi Guide"
    assert _found(client, login("u_intern"), q, title)

    resp = client.delete("/admin/documents/office-wifi-guide", headers=login("u_it_admin"))
    assert resp.status_code == 204
    assert not _found(client, login("u_intern"), q, title)
    assert (raw / "public" / "office_wifi_guide.pdf").is_file()  # file kept, just unlisted
    docs = client.get("/admin/documents", headers=login("u_it_admin")).json()
    assert "office-wifi-guide" not in {d["doc_id"] for d in docs}
