"""
FILE:         app/ingestion/parsers/xlsx_parser.py
WHAT IT DOES: Reads an Excel (.xlsx) workbook into one SheetTable per visible worksheet.
              Hidden sheets, rows and columns are removed and reported - spreadsheets can
              hide data just as PDFs can hide text.
WHERE IT FITS: Phase 4 - parsing step for .xlsx files. Column-level access rules are
              applied later, by the chunker.
USED BY:      ingestion/parsers/__init__.py (parse_document).
"""

from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from app.ingestion.elements import ParsedDocument, SheetTable


def parse_xlsx(path: Path, keep_hidden: bool = False) -> ParsedDocument:
    result = ParsedDocument()
    # data_only=True: read the computed VALUE of formula cells, not the formula text.
    wb = load_workbook(path, data_only=True)
    try:
        for ws in wb.worksheets:
            # --- hidden worksheet: skip entirely ---
            if ws.sheet_state != "visible" and not keep_hidden:
                result.hidden_text.append(f"hidden sheet '{ws.title}'")
                continue

            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                continue

            # --- hidden columns / rows: drop them, report them ---
            hidden_cols = set()
            if not keep_hidden:
                hidden_cols = {
                    i for i in range(len(rows[0]))
                    if ws.column_dimensions[get_column_letter(i + 1)].hidden
                }
            if hidden_cols:
                result.hidden_text.append(f"{len(hidden_cols)} hidden column(s) in '{ws.title}'")

            header = [
                str(h).strip() if h is not None else f"Column {i + 1}"
                for i, h in enumerate(rows[0]) if i not in hidden_cols
            ]
            data: list[list[object]] = []
            for row_no, row in enumerate(rows[1:], start=2):  # Excel rows are 1-based
                if not keep_hidden and ws.row_dimensions[row_no].hidden:
                    result.hidden_text.append(f"hidden row {row_no} in '{ws.title}'")
                    continue
                values = [v for i, v in enumerate(row) if i not in hidden_cols]
                if any(v not in (None, "") for v in values):
                    data.append(values)

            result.elements.append(SheetTable(ws.title, header, data))
    finally:
        wb.close()
    return result


def format_cell(value: object) -> str:
    """Cell value -> text for a chunk. Empty cells become ""."""
    if value is None:
        return ""
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()
