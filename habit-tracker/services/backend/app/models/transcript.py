# [review:need-review] PHASE-01/73-daily-summary-metrics-vertical
# summary: transcripts table — the one place a raw user text lives, tagged by the feature that produced it
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


class Transcript(Base):
    """
    A raw text the user handed to an LLM feature, kept exactly once.

    `source` says which feature produced it, so the table serves every text
    input the app grows without a table per feature. Deliberately narrower than
    the speech-to-text ticket will need: `duration_seconds` and `model` describe
    audio, and there is no audio here — that ticket widens this table rather
    than starting its own.

    The text is the most personal data in the app: it is written here and
    nowhere else, and never reaches a log.
    """

    __tablename__ = "transcripts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # Plain string rather than an Enum column: a new feature adds a value, and
    # an enum type would need a migration to widen on every one of them.
    source: Mapped[str] = mapped_column(String(50), index=True)
    text: Mapped[str] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        # Length only: the text itself never goes anywhere it could be logged.
        return f"<Transcript(id={self.id}, source='{self.source}', chars={len(self.text)})>"
