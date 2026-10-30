"""
PACKAGE:      app.ingestion.parsers
WHAT IT DOES: One parser per file format, behind a single entry point: parse_document().

    pdf_parser.py    PDF  -> headings, paragraphs, tables   (PyMuPDF)
    docx_parser.py   DOCX -> headings, paragraphs, tables   (python-docx)
    xlsx_parser.py   XLSX -> one SheetTable per worksheet   (openpyxl)

Every parser removes hidden content by default and lists it in ParsedDocument.hidden_text.
keep_hidden=True disables that (only for tests/investigation).
"""

from pathlib import Path

from app.ingestion.elements import ParsedDocument
from app.ingestion.parsers.docx_parser import parse_docx
from app.ingestion.parsers.pdf_parser import parse_pdf
from app.ingestion.parsers.xlsx_parser import parse_xlsx

_PARSERS = {"pdf": parse_pdf, "docx": parse_docx, "xlsx": parse_xlsx}


def parse_document(path: Path, source_type: str, keep_hidden: bool = False) -> ParsedDocument:
    try:
        parser = _PARSERS[source_type]
    except KeyError:
        raise ValueError(f"no parser for source type {source_type!r}") from None
    return parser(path, keep_hidden=keep_hidden)
