"""
FILE:         app/ingestion/models.py
WHAT IT DOES: The `documents` table - a registry of every ingested document: its file
              fingerprint (sha256), its access label, and how many chunks it produced.
WHERE IT FITS: Phase 4. Lets later phases tell what CHANGED since the last run (re-index
              only those), change a document's ACL without re-parsing it, and show admins
              what is in the system (Phase 8).
USED BY:      ingestion/pipeline.py, core/database.py (init_db creates the table).
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DocumentRecord(Base):
    __tablename__ = "documents"

    # --- identity and source ---
    doc_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    path: Mapped[str] = mapped_column(String(512))
    source_type: Mapped[str] = mapped_column(String(16))
    sha256: Mapped[str] = mapped_column(String(64))  # changes whenever the file changes

    # --- access label as last ingested (JSON lists work in SQLite and Postgres) ---
    clearance_level: Mapped[int] = mapped_column(Integer)
    departments: Mapped[list[str]] = mapped_column(JSON)
    allowed_users: Mapped[list[str]] = mapped_column(JSON)
    denied_users: Mapped[list[str]] = mapped_column(JSON)
    column_policies: Mapped[list[dict]] = mapped_column(JSON)
    contains_pii: Mapped[bool] = mapped_column(default=False)

    # --- ingestion results ---
    chunk_count: Mapped[int] = mapped_column(Integer)
    hidden_items_removed: Mapped[int] = mapped_column(Integer, default=0)
    first_ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
