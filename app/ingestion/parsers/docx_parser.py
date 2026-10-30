"""
FILE:         app/ingestion/parsers/docx_parser.py
WHAT IT DOES: Reads a Word (.docx) file into elements, in document order, using Word's
              own styles to recognise headings and bullet lists. Removes hidden text.
WHERE IT FITS: Phase 4 - parsing step for .docx files.
USED BY:      ingestion/parsers/__init__.py (parse_document).

Page headers/footers (where the classification banner lives) are not part of the body,
so they are skipped automatically.
"""

from pathlib import Path

from docx import Document
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph as DocxParagraph

from app.ingestion.elements import Element, Heading, Paragraph, ParsedDocument, TableBlock


def parse_docx(path: Path, keep_hidden: bool = False) -> ParsedDocument:
    result = ParsedDocument()
    doc = Document(str(path))

    # Walk the body in order. python-docx lists paragraphs and tables separately, so we
    # read the underlying XML children to keep text and tables interleaved correctly.
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]  # "{namespace}p" -> "p"
        element: Element | None = None
        if tag == "p":
            element = _paragraph(DocxParagraph(child, doc), result, keep_hidden)
        elif tag == "tbl":
            element = _table(DocxTable(child, doc))
        if element is not None:
            result.elements.append(element)
    return result


# =============================================================================
# PARAGRAPHS - headings, bullets, normal text; hidden runs removed
# =============================================================================
def _paragraph(p: DocxParagraph, result: ParsedDocument, keep_hidden: bool) -> Element | None:
    style = p.style.name if p.style is not None else ""
    style_hidden = bool(p.style is not None and p.style.font.hidden)

    # A "run" is a stretch of text with the same formatting. Word's hidden flag is per run.
    hidden = [r.text for r in p.runs if (r.font.hidden or style_hidden) and r.text.strip()]
    if hidden:
        result.hidden_text.append(" ".join(hidden))
    text = "".join(
        r.text for r in p.runs if keep_hidden or not (r.font.hidden or style_hidden)
    ).strip()
    if not text:
        return None

    if style == "Title":
        return Heading(text, 0)
    if style.startswith("Heading "):
        level = style.split()[-1]
        return Heading(text, min(int(level), 2) if level.isdigit() else 1)
    if "List" in style:
        return Paragraph(f"- {text}")
    return Paragraph(text)


# =============================================================================
# TABLES - first row is the header
# =============================================================================
def _table(table: DocxTable) -> TableBlock | None:
    rows = [[" ".join(cell.text.split()) for cell in row.cells] for row in table.rows]
    rows = [r for r in rows if any(r)]
    return TableBlock(rows[0], rows[1:]) if rows else None
