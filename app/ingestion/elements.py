"""
FILE:         app/ingestion/elements.py
WHAT IT DOES: The common "language" every parser outputs. Whatever the file format, a
              parsed document becomes an ordered list of these simple elements.
WHERE IT FITS: Phase 4. Parsers (PDF/DOCX/XLSX) produce elements -> the chunker turns
              elements into chunks. The chunker never needs to know the file format.
USED BY:      ingestion/parsers/*, ingestion/chunker.py.

    PDF  ──┐
    DOCX ──┼──►  [Heading, Paragraph, TableBlock, ...]  ──►  chunker
    XLSX ──┘     [SheetTable, ...]
"""

from dataclasses import dataclass, field


# =============================================================================
# 1. ELEMENTS - the building blocks of a parsed document
# =============================================================================
@dataclass(frozen=True)
class Heading:
    text: str
    level: int  # 0 = document title, 1 = section, 2 = sub-section
    page: int | None = None


@dataclass(frozen=True)
class Paragraph:
    text: str  # bullet items appear as lines starting with "- "
    page: int | None = None


@dataclass(frozen=True)
class TableBlock:
    """A table inside a PDF or Word document."""

    header: list[str]
    rows: list[list[str]]
    page: int | None = None

    # Tables are kept as Markdown so the LLM can still see rows and columns.
    def to_markdown(self, rows: list[list[str]] | None = None) -> str:
        body = self.rows if rows is None else rows
        lines = ["| " + " | ".join(self.header) + " |",
                 "|" + "---|" * len(self.header)]
        lines += ["| " + " | ".join(r) + " |" for r in body]
        return "\n".join(lines)


@dataclass(frozen=True)
class SheetTable:
    """One worksheet of a spreadsheet: header row + data rows (raw cell values)."""

    sheet: str
    header: list[str]
    rows: list[list[object]]


Element = Heading | Paragraph | TableBlock | SheetTable


# =============================================================================
# 2. PARSE RESULT - the elements plus anything suspicious found on the way
# =============================================================================
@dataclass
class ParsedDocument:
    elements: list[Element] = field(default_factory=list)
    # Text a human cannot see (white / microscopic text, hidden Word runs, hidden sheets,
    # rows or columns). Removed from the content by default and reported for review,
    # because hidden text is a classic way to smuggle prompt injections into RAG.
    hidden_text: list[str] = field(default_factory=list)
    pages: int | None = None
