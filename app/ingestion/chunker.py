"""
FILE:         app/ingestion/chunker.py
WHAT IT DOES: Cuts a parsed document into chunks and stamps every chunk with its access
              label (ACL). This is where security metadata gets attached to content.
WHERE IT FITS: Phase 4 - after parsing, before indexing (Phase 5).
USED BY:      ingestion/pipeline.py, tests.

Two strategies:
    PROSE (PDF, DOCX)  structure-aware: a new section heading always starts a new chunk;
                       long sections are split near TARGET_TOKENS with a small overlap.
                       Every chunk gets the DOCUMENT's ACL.
    SHEETS (XLSX)      rows become "Column: value | Column: value" lines. Columns are
                       grouped by ACL: unrestricted columns get the document's ACL;
                       each restricted group (e.g. salary) gets document ACL + column
                       ACL combined - so the salary text physically lives in a chunk
                       that only HR/Finance can retrieve.

Token counts are ESTIMATES (~4 characters per token for English) - no tokenizer download.
"""

import math
import re
import uuid
from dataclasses import dataclass
from datetime import datetime

from app.core.access import Clearance, ResourceACL, combine_acls
from app.ingestion.elements import Heading, Paragraph, ParsedDocument, SheetTable, TableBlock
from app.ingestion.manifest import DocumentEntry
from app.ingestion.parsers.xlsx_parser import format_cell
from app.ingestion.schemas import Chunk

# =============================================================================
# SIZE SETTINGS
# =============================================================================
TARGET_TOKENS = 300  # start a new chunk once this size would be exceeded
MAX_TOKENS = 400  # hard ceiling for a chunk body (embedding models cap at ~512)
OVERLAP_TOKENS = 60  # a short trailing paragraph is repeated in the next chunk
PIECE_MAX_TOKENS = MAX_TOKENS - OVERLAP_TOKENS  # one piece + overlap never exceeds MAX

# Fixed namespace so chunk ids are stable across runs (uuid5 = deterministic).
_CHUNK_NAMESPACE = uuid.UUID("6f1c2a52-6f6b-4b7e-9a37-0c6b1f2d9e10")


def estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


# A chunk before ids/timestamps are attached.
@dataclass
class _Draft:
    body: str
    acl: ResourceACL
    section: str | None = None
    page: int | None = None
    sheet: str | None = None
    columns: list[str] | None = None


# A unit of content the prose chunker packs into chunks.
@dataclass
class _Piece:
    text: str
    page: int | None
    is_table: bool = False


# =============================================================================
# MAIN ENTRY
# =============================================================================
def chunk_document(
    entry: DocumentEntry, parsed: ParsedDocument, doc_sha256: str, ingested_at: datetime
) -> list[Chunk]:
    # The document's own label, copied from the manifest - never invented here.
    doc_acl = ResourceACL(
        clearance_level=entry.clearance_level,
        departments=entry.departments,
        allowed_users=entry.allowed_users,
        denied_users=entry.denied_users,
    )
    if entry.source_type == "xlsx":
        drafts = _chunk_sheets(entry, parsed, doc_acl)
    else:
        drafts = _chunk_prose(entry, parsed, doc_acl)

    chunks = []
    for i, draft in enumerate(drafts):
        text = _context_header(entry.title, draft) + "\n" + draft.body
        chunks.append(Chunk(
            **draft.acl.model_dump(),  # the access label travels with every chunk
            chunk_id=str(uuid.uuid5(_CHUNK_NAMESPACE, f"{entry.doc_id}:{doc_sha256}:{i}")),
            doc_id=entry.doc_id,
            chunk_index=i,
            doc_title=entry.title,
            source_type=entry.source_type,
            source_path=entry.path,
            section=draft.section,
            page=draft.page,
            sheet=draft.sheet,
            columns=draft.columns,
            text=text,
            token_estimate=estimate_tokens(text),
            classification=Clearance(draft.acl.clearance_level).name.lower(),
            contains_pii=entry.contains_pii,
            doc_sha256=doc_sha256,
            ingested_at=ingested_at,
        ))
    return chunks


# "[Document: Employee Handbook 2026 | Section: 1. Time Off]"
def _context_header(title: str, draft: _Draft) -> str:
    parts = [f"Document: {title}"]
    if draft.sheet:
        parts.append(f"Sheet: {draft.sheet}")
    if draft.columns:
        parts.append(f"Columns: {', '.join(draft.columns)}")
    if draft.section:
        parts.append(f"Section: {draft.section}")
    return "[" + " | ".join(parts) + "]"


# =============================================================================
# STRATEGY 1: PROSE (PDF, DOCX)
# =============================================================================
def _chunk_prose(entry: DocumentEntry, parsed: ParsedDocument, acl: ResourceACL) -> list[_Draft]:
    drafts: list[_Draft] = []
    path: list[str] = []  # current heading path, e.g. ["3. Expenses"]
    buffer: list[_Piece] = []

    def flush() -> None:
        if buffer:
            drafts.append(_Draft(
                body="\n\n".join(p.text for p in buffer),
                acl=acl,
                section=" > ".join(path) or None,
                page=buffer[0].page,
            ))
            buffer.clear()

    for element in parsed.elements:
        # --- headings: close the current chunk, update the section path ---
        if isinstance(element, Heading):
            flush()
            if element.level == 0:
                path = []  # the document title is already in every context header
            elif element.level == 1:
                path = [element.text]
            else:
                path = path[:1] + [element.text]
            continue

        # --- content: break into pieces no bigger than PIECE_MAX_TOKENS ---
        if isinstance(element, Paragraph):
            pieces = [_Piece(t, element.page) for t in _split_text(element.text)]
        elif isinstance(element, TableBlock):
            pieces = [_Piece(t, element.page, True) for t in _split_table(element)]
        else:
            continue

        # --- pack pieces into chunks of about TARGET_TOKENS ---
        for piece in pieces:
            used = sum(estimate_tokens(p.text) for p in buffer)
            if buffer and used + estimate_tokens(piece.text) > TARGET_TOKENS:
                last = buffer[-1]
                flush()
                # Overlap: repeat a short trailing paragraph so context isn't cut mid-thought.
                if not last.is_table and estimate_tokens(last.text) <= OVERLAP_TOKENS:
                    buffer.append(last)
            buffer.append(piece)
    flush()
    return drafts


# Split a long paragraph at sentence boundaries (or, for one giant sentence, at words).
def _split_text(text: str) -> list[str]:
    if estimate_tokens(text) <= PIECE_MAX_TOKENS:
        return [text]
    pieces, current = [], ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        for word_group in _split_words(sentence):
            candidate = f"{current} {word_group}".strip()
            if current and estimate_tokens(candidate) > PIECE_MAX_TOKENS:
                pieces.append(current)
                current = word_group
            else:
                current = candidate
    if current:
        pieces.append(current)
    return pieces


def _split_words(sentence: str) -> list[str]:
    if estimate_tokens(sentence) <= PIECE_MAX_TOKENS:
        return [sentence]
    groups, current = [], []
    for word in sentence.split():
        if current and estimate_tokens(" ".join([*current, word])) > PIECE_MAX_TOKENS:
            groups.append(" ".join(current))
            current = []
        current.append(word)
    return groups + [" ".join(current)] if current else groups


# Split a big table into row groups; every group repeats the header row.
def _split_table(table: TableBlock) -> list[str]:
    if estimate_tokens(table.to_markdown()) <= PIECE_MAX_TOKENS:
        return [table.to_markdown()]
    pieces, rows = [], []
    for row in table.rows:
        if rows and estimate_tokens(table.to_markdown([*rows, row])) > PIECE_MAX_TOKENS:
            pieces.append(table.to_markdown(rows))
            rows = []
        rows.append(row)
    if rows:
        pieces.append(table.to_markdown(rows))
    return pieces


# =============================================================================
# STRATEGY 2: SPREADSHEETS (XLSX) - column groups by access label
# =============================================================================
def _chunk_sheets(
    entry: DocumentEntry, parsed: ParsedDocument, doc_acl: ResourceACL
) -> list[_Draft]:
    restricted = {c for p in entry.column_policies for c in p.columns}
    drafts: list[_Draft] = []

    for sheet in parsed.elements:
        if not isinstance(sheet, SheetTable):
            continue
        header = sheet.header
        keys = [c for c in (entry.key_columns or header[:1]) if c in header]

        # --- GROUP A: every unrestricted column, under the document's own label ---
        groups: list[tuple[list[str], ResourceACL]] = []
        base = [c for c in header if c not in restricted]
        if base:
            groups.append((base, doc_acl))

        # --- GROUP B..: each restricted column set + key columns, under the COMBINED
        #     label (document AND column rule must both pass) ---
        for policy in entry.column_policies:
            cols = [c for c in policy.columns if c in header]
            if cols:
                groups.append(([k for k in keys if k not in restricted] + cols,
                               combine_acls(doc_acl, policy)))

        for columns, acl in groups:
            drafts += _sheet_drafts(sheet, columns, keys, acl)
    return drafts


def _sheet_drafts(
    sheet: SheetTable, columns: list[str], keys: list[str], acl: ResourceACL
) -> list[_Draft]:
    index = [sheet.header.index(c) for c in columns]
    value_columns = set(columns) - set(keys) or set(columns)

    # One line per row: "Employee ID: EMP-1007 | Name: Lena Okafor | Base Salary (USD): 92500"
    lines = []
    for row in sheet.rows:
        pairs = [(sheet.header[i], format_cell(row[i])) for i in index if i < len(row)]
        pairs = [(name, value) for name, value in pairs if value]
        if any(name in value_columns for name, _ in pairs):  # skip rows with nothing to say
            lines.append(" | ".join(f"{name}: {value}" for name, value in pairs))

    # Pack lines into chunks of about TARGET_TOKENS.
    drafts, current = [], []
    for line in lines:
        if current and estimate_tokens("\n".join([*current, line])) > TARGET_TOKENS:
            drafts.append(_Draft("\n".join(current), acl, sheet=sheet.sheet, columns=columns))
            current = []
        current.append(line)
    if current:
        drafts.append(_Draft("\n".join(current), acl, sheet=sheet.sheet, columns=columns))
    return drafts
