# [review:need-review] PHASE-01/74-daily-summary-journal
# summary: applied_daily_summaries — one row per successfully applied day, keyed by Idempotency-Key, carrying the response the original apply returned
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


class AppliedDailySummary(Base):
    """
    The receipt of one applied day: what was written, under which client key.

    Idempotency needs a carrier that exists whatever the apply wrote. Hanging
    the key on the created entries only works for a day that had metrics; a day
    that was nothing but text left nothing to recognise a replay by, so a second
    click appended the retelling to itself. This row is written in the same
    transaction as the metrics and the journal, so it exists exactly when the
    day was applied and never when it was rolled back.

    `entry_ids` and `journal_entry_id` are the response as it was first sent.
    Storing it rather than recomputing it keeps a replay's answer byte-identical
    to the original, including the order of the ids.

    `journal_entry_id` carries no foreign key on purpose: the journal entry can
    be deleted later through the journal API, and that must not erase the fact
    that the day was applied — it would make the key reusable and let the
    retelling be written a second time.
    """

    __tablename__ = "applied_daily_summaries"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # The client-supplied key, unique on its own: one key applies one day. Not
    # nullable, unlike `entries.idempotency_key` — a row here exists only
    # because a key was given.
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)

    entry_date: Mapped[date] = mapped_column(Date, index=True)

    # The ids the original apply returned, in the order it returned them.
    entry_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    journal_entry_id: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        # The key is client data; only its presence is worth printing.
        return (
            f"<AppliedDailySummary(id={self.id}, date={self.entry_date}, "
            f"entries={len(self.entry_ids)})>"
        )
