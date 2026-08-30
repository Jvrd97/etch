# [review:need-review] PHASE-03/90
# summary: `day_summary` — the verdict of a day with the rule it was reached under, the counters behind it, the prose made searchable by a generated tsvector, and the CHECK that makes an override without a note impossible for every writer
from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base
from app.day.evaluate import VERDICTS
from app.models.checks import in_list

# The generated column, spelled once so the model and the migration cannot
# drift. A two-argument `to_tsvector` is immutable, which is what lets postgres
# store it rather than recompute it on every read.
SEARCH_EXPR = "to_tsvector('russian', body_md)"

# Where the row came from. `close` is a day a person (or the agent on their
# behalf) closed here; `import` is a verdict that arrived as prose from
# `personal-os` and was never computed. The distinction is what makes
# «импортированные вердикты не пересчитываются» expressible at all: without it
# a recompute has no way to tell a judgement it may redo from one it may not.
SOURCE_CLOSE = "close"
SOURCE_IMPORT = "import"
SUMMARY_SOURCES: tuple[str, ...] = (SOURCE_CLOSE, SOURCE_IMPORT)


class DaySummary(Base):
    """
    The итог of one day: what the verdict was, and everything it stands on.

    **Наличие строки и есть «день закрыт».** No column of its own: a boolean
    beside a row that exists would be a second answer to the same question, and
    the two would eventually disagree. `GET /day/{date}` answers with a live
    recount and `verdict = null` while there is no row here, which is how «не
    закрыл» stays a different fact from «проиграл». The *stage* of closing —
    started, half-done — is `#143` and adds a column to this table rather than a
    table of its own.

    **`rule_set_id` is stored, not derived.** The canon changed on 2026-08-17
    and will change again; a verdict that does not carry the numbers it was
    measured against cannot be re-read a month later, and re-deriving it on
    display would silently re-judge the past.

    **Проза никуда не девается.** «Что случилось вместо плана», «Что мешало» и
    оговорка «цифра 0/4 измеряет не работу, а её видимость» — половина ценности
    записи, and `body_md` with a generated `tsvector` and a GIN index is what
    keeps it findable instead of merely stored.

    **Переопределение вердикта требует записки, и это правило базы.** The
    Pydantic validator is a message; this CHECK is the rule. Человек имеет право
    сказать «день был выигран, просто я не отметил» — но вслух, а не молчаливой
    правкой, and that has to hold for a `psql` session as much as for the API.
    """

    __tablename__ = "day_summary"
    __table_args__ = (
        CheckConstraint(in_list("verdict", VERDICTS), name="ck_day_summary_verdict"),
        CheckConstraint(
            in_list("source", SUMMARY_SOURCES), name="ck_day_summary_source"
        ),
        CheckConstraint(
            "NOT verdict_override OR verdict_override_note IS NOT NULL",
            name="ck_day_summary_override_has_note",
        ),
        Index("ix_day_summary_search", "search", postgresql_using="gin"),
    )

    # The day is the key: one итог per date, replaced in place. The attribute is
    # not called `date` for the reason `Day.day_date` is not — see that model.
    day_date: Mapped[date_type] = mapped_column(
        "day_date", Date, ForeignKey("day.date", ondelete="CASCADE"), primary_key=True
    )
    rule_set_id: Mapped[int] = mapped_column(ForeignKey("day_rule_set.id"))

    # NULL while nothing judged the day — an imported summary whose prose says
    # «вне игры (выходной)» is exactly that, and so is a row `#143` will write
    # for a closing that was started and not finished.
    verdict: Mapped[str | None] = mapped_column(Text, nullable=True)
    verdict_reason: Mapped[str] = mapped_column(Text, server_default="")

    verdict_override: Mapped[bool] = mapped_column(Boolean, server_default="false")
    verdict_override_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    anchors_done: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    anchors_total: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    tasks_done: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    tasks_total: Mapped[int] = mapped_column(SmallInteger, server_default="0")

    # NULL means "не измерено", never zero. Intervals of work are `#91`; until
    # then the number arrives in the body of `POST /close` or not at all.
    work_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Derived from the verdicts of every earlier day, recomputed as a whole —
    # stored because the screen reads it per day and a running fold on every
    # render would be the second place a streak is computed.
    streak_after: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # The three questions `/day-close` asks and nothing else records: писал ли
    # сам, сколько вопросов Education висит, сделано ли ревью.
    wrote_from_scratch: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    education_debt: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    reviewed_today: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    body_md: Mapped[str] = mapped_column(Text, server_default="")
    # What the day could not be judged on, as machine codes. The Russian a
    # person reads lives in `lib/day-format.ts`, the way `verdict_reason` does.
    missing_data: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default="{}"
    )
    source: Mapped[str] = mapped_column(Text, server_default=SOURCE_CLOSE)

    search: Mapped[Any] = mapped_column(
        TSVECTOR, Computed(SEARCH_EXPR, persisted=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<DaySummary(day_date={self.day_date}, verdict={self.verdict!r})>"
