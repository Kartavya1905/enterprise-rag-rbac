"""
FILE:         scripts/dataset/render.py
WHAT IT DOES: Turns document content into real files: PDF, Word (DOCX) and Excel (XLSX).
WHERE IT FITS: Phase 2 - STEP 3 of the dataset pipeline. Content is written once as simple
              "blocks" (heading, paragraph, bullets, table ...); this file decides how each
              block looks in each format.
USED BY:      scripts/generate_dataset.py.

    content.py blocks  ->  write_pdf()   ->  .pdf   (library: fpdf2)
                       ->  write_docx()  ->  .docx  (library: python-docx)
    content.py sheets  ->  write_xlsx()  ->  .xlsx  (library: openpyxl)
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from docx import Document as DocxDocument
from fpdf import FPDF, XPos, YPos
from openpyxl import Workbook
from openpyxl.styles import Font

# Fixed so regenerating the dataset produces stable file metadata.
CREATED_AT = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
AUTHOR = "Orbitra Systems (synthetic data)"


# =============================================================================
# 1. CONTENT BLOCKS - the building pieces of a PDF/DOCX document
# =============================================================================
@dataclass(frozen=True)
class H1:  # big section heading
    text: str


@dataclass(frozen=True)
class H2:  # smaller sub-heading
    text: str


@dataclass(frozen=True)
class P:  # paragraph
    text: str


@dataclass(frozen=True)
class Bullets:  # bullet list
    items: list[str]


@dataclass(frozen=True)
class Table:  # table with a header row
    header: list[str]
    rows: list[list[str]]


@dataclass(frozen=True)
class Hidden:
    """Text invisible to a human reader (white 1pt in PDF, hidden runs in DOCX).

    Used to plant prompt-injection payloads that a naive parser will still extract.
    """

    text: str


Block = H1 | H2 | P | Bullets | Table | Hidden


# One worksheet of a spreadsheet: a header row plus data rows.
@dataclass(frozen=True)
class Sheet:
    name: str
    header: list[str]
    rows: list[list[object]]


# =============================================================================
# 2. PDF WRITER
# =============================================================================
# FPDF subclass that prints the classification banner (e.g. "RESTRICTED - ...") at the
# top of every page and a page number at the bottom, like real company documents.
class _BannerPDF(FPDF):
    def __init__(self, banner: str) -> None:
        super().__init__()
        self.banner = banner

    def header(self) -> None:  # called automatically on every new page
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(160, 0, 0)  # dark red
        self.cell(0, 6, self.banner, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(0, 0, 0)
        self.ln(2)

    def footer(self) -> None:  # called automatically at the end of every page
        self.set_y(-12)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 6, f"Orbitra Systems - page {self.page_no()}", align="C")
        self.set_text_color(0, 0, 0)


def _latin1(text: str) -> str:
    # fpdf2 core fonts are latin-1 only; fail loudly instead of writing mojibake.
    text.encode("latin-1")
    return text


def write_pdf(path: Path, title: str, banner: str, blocks: list[Block]) -> None:
    # --- Set up the document and its metadata ---
    pdf = _BannerPDF(banner)
    pdf.set_title(title)
    pdf.set_author(AUTHOR)
    pdf.set_creation_date(CREATED_AT)
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Write one wrapped line/paragraph, then move back to the left margin.
    def line(text: str, style: str = "", size: int = 10, height: float = 5) -> None:
        pdf.set_font("Helvetica", style, size)
        pdf.multi_cell(0, height, _latin1(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # --- Title, then each block in order ---
    line(title, "B", 18, 9)
    pdf.ln(3)
    for block in blocks:
        match block:
            case H1(text):
                pdf.ln(2)
                line(text, "B", 14, 8)
            case H2(text):
                pdf.ln(1)
                line(text, "B", 11, 6)
            case P(text):
                line(text)
                pdf.ln(2)
            case Bullets(items):
                for item in items:
                    line(f"  - {item}")
                pdf.ln(2)
            case Table(header, rows):
                pdf.set_font("Helvetica", "", 9)
                with pdf.table(line_height=5) as table:  # first row = bold header
                    for cells in [header, *rows]:
                        row = table.row()
                        for cell in cells:
                            row.cell(_latin1(cell))
                pdf.ln(3)
            case Hidden(text):
                # THE POISON: white text, 1pt tall - invisible on screen and in print,
                # but text extraction (what RAG ingestion does) still picks it up.
                pdf.set_text_color(255, 255, 255)
                line(text, size=1, height=1)
                pdf.set_text_color(0, 0, 0)

    # --- Save ---
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(path))


# =============================================================================
# 3. WORD (DOCX) WRITER - same blocks, Word formatting
# =============================================================================
def write_docx(path: Path, title: str, banner: str, blocks: list[Block]) -> None:
    # --- Set up the document, its metadata, and the page-header banner ---
    doc = DocxDocument()
    props = doc.core_properties
    props.title, props.author, props.created = title, AUTHOR, CREATED_AT.replace(tzinfo=None)
    doc.sections[0].header.paragraphs[0].text = banner

    # --- Title, then each block in order ---
    doc.add_heading(title, level=0)
    for block in blocks:
        match block:
            case H1(text):
                doc.add_heading(text, level=1)
            case H2(text):
                doc.add_heading(text, level=2)
            case P(text):
                doc.add_paragraph(text)
            case Bullets(items):
                for item in items:
                    doc.add_paragraph(item, style="List Bullet")
            case Table(header, rows):
                table = doc.add_table(rows=1, cols=len(header), style="Table Grid")
                for cell, text in zip(table.rows[0].cells, header, strict=True):
                    cell.text = text
                    cell.paragraphs[0].runs[0].bold = True  # bold header row
                for values in rows:
                    for cell, text in zip(table.add_row().cells, values, strict=True):
                        cell.text = text
            case Hidden(text):
                # Word's own "hidden text" flag - not shown, but parsers can read it.
                doc.add_paragraph().add_run(text).font.hidden = True

    # --- Save ---
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))


# =============================================================================
# 4. EXCEL (XLSX) WRITER - one worksheet per Sheet
# =============================================================================
def write_xlsx(path: Path, title: str, classification: str, sheets: list[Sheet]) -> None:
    # --- Workbook metadata (classification stored in the file's keywords) ---
    wb = Workbook()
    wb.remove(wb.active)  # drop the default empty sheet
    wb.properties.title = title
    wb.properties.creator = AUTHOR
    wb.properties.created = CREATED_AT.replace(tzinfo=None)
    wb.properties.keywords = classification

    for spec in sheets:
        # --- Header row (bold) + data rows ---
        ws = wb.create_sheet(spec.name)
        ws.append(spec.header)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for row in spec.rows:
            ws.append(row)

        # --- Cosmetics: header stays visible when scrolling; columns sized to fit ---
        ws.freeze_panes = "A2"
        for i, name in enumerate(spec.header, start=1):
            width = max([len(str(name))] + [len(str(r[i - 1])) for r in spec.rows])
            ws.column_dimensions[ws.cell(1, i).column_letter].width = min(width + 2, 40)

    # --- Save ---
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(path))
