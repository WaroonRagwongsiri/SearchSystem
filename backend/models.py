from typing import Optional

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # item UUID, unique across all files
    json_data: Mapped[dict] = mapped_column(JSONB, nullable=False)


class Dictionary(Base):
    __tablename__ = "dictionary"

    ancient_word: Mapped[str] = mapped_column(String, primary_key=True)
    modern_definition: Mapped[str] = mapped_column(Text, nullable=False)
    # Clean modern Thai equivalent extracted (by LLM) from the raw scholarly
    # modern_definition entry. Nullable: empty until the extraction pipeline runs.
    modern_word: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
