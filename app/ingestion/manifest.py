"""
FILE:         app/ingestion/manifest.py
WHAT IT DOES: Loads and validates data/raw/manifest.yaml - the list of every source
              document and the access label (ACL) an admin assigned to it.
WHERE IT FITS: Phase 2 created it. In Phase 4, ingestion reads this manifest and copies
              each document's ACL onto every chunk cut from that document, so search
              (Phase 6) knows what to hide from whom.
USED BY:      scripts/generate_dataset.py, tests, and (Phase 4) the ingestion pipeline.

Flow:  manifest.yaml  ->  Manifest (validated)  ->  DocumentEntry per file
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from app.core.access import ResourceACL, UnsupportedACLCombination, combine_acls

SourceType = Literal["pdf", "docx", "xlsx"]


# =============================================================================
# 1. COLUMN POLICY - stricter rules for specific spreadsheet columns
# =============================================================================
class ColumnPolicy(ResourceACL):
    """Stricter ACL for specific spreadsheet columns (e.g. salary in a staff directory).

    Columns not covered by a policy inherit the document's ACL.
    """

    columns: list[str] = Field(min_length=1)  # e.g. ["Base Salary (USD)"]


# =============================================================================
# 2. DOCUMENT ENTRY - one file + its access label
# =============================================================================
# Inherits clearance_level / departments / allowed_users / denied_users from ResourceACL.
class DocumentEntry(ResourceACL):
    doc_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")  # e.g. "payroll-2026-q3"
    path: str  # relative to the raw data directory, POSIX style
    title: str
    source_type: SourceType
    owner: str  # the person responsible for the document
    contains_pii: bool = False  # personal data (salaries, tax IDs ...)
    column_policies: list[ColumnPolicy] = Field(default_factory=list)
    # Spreadsheets: columns that identify a row (e.g. Employee ID, Name). They are repeated
    # in restricted-column chunks so "Base Salary: 92500" says WHOSE salary it is.
    # Defaults to the first column. Must not themselves be restricted.
    key_columns: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)  # e.g. "poisoned" (test fixtures)

    # --- Validation: catch admin mistakes when the manifest loads ---
    @model_validator(mode="after")
    def _check_consistency(self) -> "DocumentEntry":
        # "report.pdf" must be declared as source_type pdf.
        if Path(self.path).suffix.lstrip(".") != self.source_type:
            raise ValueError(f"{self.doc_id}: path extension does not match {self.source_type}")
        # Column rules only make sense for spreadsheets.
        if self.column_policies and self.source_type != "xlsx":
            raise ValueError(f"{self.doc_id}: column policies only apply to spreadsheets")
        for policy in self.column_policies:
            # A column policy may only tighten access, never loosen it.
            if policy.clearance_level < self.clearance_level:
                raise ValueError(f"{self.doc_id}: column policy is looser than the document")
            # Chunking will merge document + column labels; check now that it can.
            try:
                combine_acls(self, policy)
            except UnsupportedACLCombination as exc:
                raise ValueError(f"{self.doc_id}: {exc}") from exc
        restricted = {c for p in self.column_policies for c in p.columns}
        if restricted & set(self.key_columns):
            raise ValueError(f"{self.doc_id}: a key column cannot also be restricted")
        return self


# =============================================================================
# 3. THE WHOLE MANIFEST
# =============================================================================
class Manifest(BaseModel):
    company: str
    documents: list[DocumentEntry]

    # Two documents with the same id would make chunk labels ambiguous.
    @model_validator(mode="after")
    def _check_unique_ids(self) -> "Manifest":
        ids = [d.doc_id for d in self.documents]
        duplicates = {i for i in ids if ids.count(i) > 1}
        if duplicates:
            raise ValueError(f"duplicate doc_id(s): {sorted(duplicates)}")
        return self

    # Look up one document by id: manifest.get("payroll-2026-q3")
    def get(self, doc_id: str) -> DocumentEntry:
        for doc in self.documents:
            if doc.doc_id == doc_id:
                return doc
        raise KeyError(doc_id)


# =============================================================================
# 4. LOAD - read YAML, validate, and confirm every listed file really exists
# =============================================================================
def load_manifest(manifest_path: Path, raw_dir: Path | None = None) -> Manifest:
    """Load and validate a manifest; also checks every referenced file exists."""
    manifest = Manifest.model_validate(yaml.safe_load(manifest_path.read_text(encoding="utf-8")))
    raw_dir = raw_dir or manifest_path.parent  # paths are relative to the manifest's folder
    missing = [d.path for d in manifest.documents if not (raw_dir / d.path).is_file()]
    if missing:
        raise FileNotFoundError(f"manifest references missing files: {missing}")
    return manifest
