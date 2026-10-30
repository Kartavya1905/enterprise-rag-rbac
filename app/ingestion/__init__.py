"""
PACKAGE: app.ingestion - getting documents into the system, each piece carrying its ACL.

    manifest.py   loads each document's access label (ACL)                (Phase 2)
    elements.py   the common output of all parsers: Heading, Paragraph, ...  (Phase 4)
    parsers/      PDF / DOCX / XLSX -> elements; hidden content removed    (Phase 4)
    chunker.py    elements -> chunks, each stamped with its ACL            (Phase 4)
    schemas.py    Chunk - the unit that is searched and sent to the LLM    (Phase 4)
    models.py     `documents` table - registry of what was ingested        (Phase 4)
    pipeline.py   ingest(): manifest -> parse -> chunk -> register -> chunks.jsonl

Flow:
    manifest.yaml + data/raw/*  ->  parsers  ->  chunker  ->  data/processed/chunks.jsonl
                                                         ->  `documents` table
"""
