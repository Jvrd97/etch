# [review:need-review] PHASE-03/94
# summary: `week` — the fixed snapshot of a week with `computed_at` beside its counters and the prose of its ретро kept apart from them, and `week_review_item` — the sunday checklist as rows rather than as checkboxes inside markdown
from __future__ import annotations

import uuid
from datetime import date as date_type
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base

# Length of `2026-W35`, and the reason the column is not unbounded text: the
# code is a primary key, a URL segment and a file name all at once.
ISO_CODE_LENGTH = 8

# The generated column, spelled once so the model and the migration cannot
# drift. Four prose columns rather than one, because a person searching «что
# мешало» is looking for a different thing than a person searching the mgmt
# ретро — and the four are `NOT NULL DEFAULT ''`, which is what lets them be
# concatenated without `coalesce` turning the whole vector into NULL.
SEARCH_EXPR = (
    "to_tsvector('russian', "
    "retro_md || ' ' || blockers_md || ' ' || mgmt_retro_md "
    "|| ' ' || weekly_number_md)"
)


class Week(Base):
    """
    One week, as it was true at the moment somebody computed it.

    **Неделя — снимок, а не выборка на лету.** The counters could be a `SELECT`
    over `day_summary` on every read, and they are not. Ретро утверждает то, что
    было верно, когда его писали: «0 из 7», «стрик 0, держится с 20.08». Reopen
    a day of that week in November, recompute, and a live query would silently
    make the prose beside it wrong. A stored `won_days` with `computed_at` next
    to it says instead when the numbers were last taken, and the prose keeps
    referring to a state a reader can date.

    **Проза и счётчики разведены по разным колонкам, и пересчёт трогает только
    вторые.** `recompute_week` writes `won_days`, `total_days`, `streak_end` and
    `computed_at`; `retro_md`, `blockers_md`, `mgmt_retro_md` and
    `weekly_number_md` are written only by a person (or by the import of
    `weeks/**/*.md`). That separation is the whole reason the table has ten
    columns instead of two.

    **Строка существует до того, как ретро написано.** A week nobody has
    reviewed still has days, a count of won ones and a streak at its end, and
    `GET /weeks/{iso}` answers with them rather than 404ing. «Ретро не написано»
    is `retro_md = ''`, which is a fact about the week, not an absence of it.
    """

    __tablename__ = "week"
    __table_args__ = (Index("ix_week_search", "search", postgresql_using="gin"),)

    # `2026-W35` — what the file was called, what the URL says, and what a
    # person calls the week out loud. ISO weeks run Monday to Sunday; the
    # translation to dates lives in `app.day.week` and nowhere else.
    iso_code: Mapped[str] = mapped_column(String(ISO_CODE_LENGTH), primary_key=True)

    # Materialised from `iso_code` by `app.day.week.week_bounds` when the row is
    # written. Stored so a range query over days does not have to re-derive the
    # ISO calendar in SQL — which would be the second definition of where a week
    # begins, and the first one to disagree about 2026-01-01.
    starts_on: Mapped[date_type] = mapped_column(Date)
    ends_on: Mapped[date_type] = mapped_column(Date)

    # Days of the week whose итог says `won`, and days that exist at all. The
    # denominator counts `day` rows rather than summaries: a week whose Tuesday
    # was never closed is «1 из 7», not «1 из 1».
    won_days: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    total_days: Mapped[int] = mapped_column(SmallInteger, server_default="0")

    # The streak after the last closed day of the week. NULL means no day of
    # this week was closed, which is not the same as a streak of zero — «стрик
    # 0» is a statement about days that were judged.
    streak_end: Mapped[int | None] = mapped_column(Integer, nullable=True)

    retro_md: Mapped[str] = mapped_column(Text, server_default="")
    blockers_md: Mapped[str] = mapped_column(Text, server_default="")
    mgmt_retro_md: Mapped[str] = mapped_column(Text, server_default="")
    # The Friday anchor: the weekly work report and the figure from the equation
    # of cost against value. Its own column because it is the one part of the
    # week that is due on Friday rather than on Sunday.
    weekly_number_md: Mapped[str] = mapped_column(Text, server_default="")

    # When the counters above were last taken. Moves on every recompute and on
    # nothing else, so a reader can tell whether the numbers still describe the
    # days as they are now.
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    search: Mapped[Any] = mapped_column(
        TSVECTOR, Computed(SEARCH_EXPR, persisted=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    review_items: Mapped[list[WeekReviewItem]] = relationship(
        back_populates="week",
        cascade="all, delete-orphan",
        order_by="WeekReviewItem.ord",
    )

    def __repr__(self) -> str:
        return f"<Week({self.iso_code}, won={self.won_days}/{self.total_days})>"


class WeekReviewItem(Base):
    """
    One line of «На разбор в воскресенье», with its own tick.

    Rows rather than checkboxes inside `retro_md`: the point of the list is that
    a question either got answered on Sunday or moved to the next week, and a
    `- [ ]` inside prose can only be counted by a regular expression — which is
    precisely how `life.py` came to be unable to tell «не закрыт» from
    «проигран».
    """

    __tablename__ = "week_review_item"
    __table_args__ = (
        UniqueConstraint("week_iso", "ord", name="uq_week_review_item_week_ord"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    week_iso: Mapped[str] = mapped_column(
        String(ISO_CODE_LENGTH),
        ForeignKey("week.iso_code", ondelete="CASCADE"),
        index=True,
    )
    ord: Mapped[int] = mapped_column(SmallInteger)
    text_md: Mapped[str] = mapped_column(Text)
    done: Mapped[bool] = mapped_column(Boolean, server_default="false")

    week: Mapped[Week] = relationship(back_populates="review_items")

    def __repr__(self) -> str:
        return f"<WeekReviewItem({self.week_iso}#{self.ord}, done={self.done})>"
