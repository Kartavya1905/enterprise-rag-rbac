"""
FILE:         app/ingestion/parsers/pdf_parser.py
WHAT IT DOES: Reads a PDF into elements (headings, paragraphs, tables) using PyMuPDF, while
              removing page furniture (banners, page numbers) and hidden text.
WHERE IT FITS: Phase 4 - parsing step for .pdf files.
USED BY:      ingestion/parsers/__init__.py (parse_document).

Per page:
    STEP 1  find tables -> read each CELL's text by its position (keeps spaces intact)
    STEP 2  read every other text line with its font size, boldness and colour
    STEP 3  drop hidden text (white or microscopic) and page furniture (tiny margin text)
    STEP 4  classify each text block: heading (big/bold) or paragraph
    STEP 5  put tables and text back in top-to-bottom reading order
"""

from pathlib import Path

import pymupdf

from app.ingestion.elements import Element, Heading, Paragraph, ParsedDocument, TableBlock

# =============================================================================
# TUNING CONSTANTS
# =============================================================================
WHITE = 0xFFFFFF  # text colour of invisible-on-white text
MIN_VISIBLE_SIZE = 3.0  # pt; smaller text is unreadable -> treated as hidden
MARGIN_FRACTION = 0.08  # top/bottom 8% of the page = header/footer zone
FURNITURE_MAX_SIZE = 8.5  # pt; small text in that zone = banner / page number
TITLE_MIN_SIZE = 16.0  # pt; bigger = document title
H1_MIN_SIZE = 13.0  # pt; bigger = section heading
H2_MIN_SIZE = 10.5  # pt; bold and at least this = sub-heading


def _is_hidden(span: dict) -> bool:
    return span["color"] == WHITE or span["size"] < MIN_VISIBLE_SIZE


def _is_bold(span: dict) -> bool:
    return bool(span["flags"] & 16) or "bold" in span["font"].lower()


def _clean(text: str) -> str:
    return " ".join(text.split())  # collapse line breaks / repeated spaces


# =============================================================================
# MAIN ENTRY
# =============================================================================
def parse_pdf(path: Path, keep_hidden: bool = False) -> ParsedDocument:
    result = ParsedDocument()
    with pymupdf.open(path) as doc:
        result.pages = doc.page_count
        for page_no, page in enumerate(doc, start=1):
            result.elements.extend(_parse_page(page, page_no, result, keep_hidden))
    return result


def _parse_page(
    page: pymupdf.Page, page_no: int, result: ParsedDocument, keep_hidden: bool
) -> list[Element]:
    positioned: list[tuple[float, Element]] = []  # (y position, element) for sorting

    # --- STEP 1: tables. PyMuPDF's own table text drops spaces on some PDFs
    #     ("OrbitraFleet30"), so we only use it for cell BOUNDARIES and read each
    #     cell's text ourselves. Wrapped cell lines are joined with a space. ---
    tables = page.find_tables().tables
    table_areas = [pymupdf.Rect(t.bbox) for t in tables]
    for table in tables:
        rows = [
            [_clean(page.get_text("text", clip=pymupdf.Rect(c))) if c else "" for c in row.cells]
            for row in table.rows
        ]
        rows = [r for r in rows if any(r)]
        if rows:
            positioned.append((table.bbox[1], TableBlock(rows[0], rows[1:], page_no)))

    # --- STEP 2-4: all text outside tables, block by block ---
    height = page.rect.height
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:  # 0 = text; images etc. are skipped
            continue
        box = pymupdf.Rect(block["bbox"])
        center = pymupdf.Point((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2)
        if any(area.contains(center) for area in table_areas):
            continue  # already captured as part of a table

        lines: list[tuple[str, float, bool, float]] = []  # (text, size, bold, y)
        hidden_in_block: list[str] = []
        for line in block["lines"]:
            spans = [s for s in line["spans"] if s["text"].strip()]
            # STEP 3a: hidden text - removed and reported (unless keep_hidden)
            hidden_in_block += [s["text"].strip() for s in spans if _is_hidden(s)]
            visible = spans if keep_hidden else [s for s in spans if not _is_hidden(s)]
            if not visible:
                continue
            size = max(s["size"] for s in visible)
            y0, y1 = line["bbox"][1], line["bbox"][3]
            # STEP 3b: page furniture - small text in the top/bottom margin zone
            in_margin = y1 < height * MARGIN_FRACTION or y0 > height * (1 - MARGIN_FRACTION)
            if in_margin and size <= FURNITURE_MAX_SIZE:
                continue
            text = "".join(s["text"] for s in visible).strip()
            lines.append((text, size, all(_is_bold(s) for s in visible), y0))

        if hidden_in_block:
            result.hidden_text.append(" ".join(hidden_in_block))
        if lines:
            positioned.append((lines[0][3], _block_to_element(lines, page_no)))

    # --- STEP 5: reading order = top to bottom ---
    positioned.sort(key=lambda item: item[0])
    return [element for _, element in positioned]


# STEP 4: decide whether a block of lines is a heading or a paragraph.
def _block_to_element(lines: list[tuple[str, float, bool, float]], page_no: int) -> Element:
    size = max(size for _, size, _, _ in lines)
    bold = all(bold for _, _, bold, _ in lines)
    texts = [text for text, _, _, _ in lines]

    if size >= H1_MIN_SIZE or (bold and size >= H2_MIN_SIZE):
        level = 0 if size >= TITLE_MIN_SIZE else 1 if size >= H1_MIN_SIZE else 2
        return Heading(" ".join(texts), level, page_no)

    # Paragraph: wrapped lines are re-joined; bullet items ("- ...") keep their own line.
    parts: list[str] = []
    for text in texts:
        if text.startswith("- ") or not parts:
            parts.append(text)
        else:
            parts[-1] += " " + text
    return Paragraph("\n".join(parts), page_no)
