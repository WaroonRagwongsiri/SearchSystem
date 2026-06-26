from typing import Optional

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # item UUID, unique across all files
    json_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # ponytail: app runs raw SQL (see migrate_embed_text.sql); declared here for ORM completeness.
    # The text actually embedded — /reembed + the embed pipeline write it; NULL ⇒ fall back to
    # modernized_content (the read-only LLM output). Lets a human override what gets vectorized.
    embed_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Dictionary(Base):
    __tablename__ = "dictionary"

    ancient_word: Mapped[str] = mapped_column(String, primary_key=True)
    modern_definition: Mapped[str] = mapped_column(Text, nullable=False)
    # Clean modern Thai equivalent extracted (by LLM) from the raw scholarly
    # modern_definition entry. Nullable: empty until the extraction pipeline runs.
    modern_word: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Extraction-pipeline status of the modern_word above. NOTE: Base.metadata.create_all
    # will NOT add these to an existing table — run backend/migrate_dictionary_status.sql.
    status: Mapped[Optional[str]] = mapped_column(Text, default="pending")  # pending | done | failed
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # set only when status='failed'
