# [review:need-review] PHASE-03/91
# summary: `work_interval` — one recorded stretch of work or pause, keyed to the day its start belongs to, with the agent's original proposal kept beside a corrected one and no window title anywhere in the table
from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    literal_column,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy.sql.elements import ColumnClause

from app.core.database import Base
from app.day.work import MODES, SOURCES

# The interval as postgres understands ranges. An open interval — `ended_at
# IS NULL` — becomes an unbounded upper end, which is exactly what "идёт прямо
# сейчас" means, and the GiST index over it is what makes "какие интервалы
# накрывают этот момент" a lookup rather than a scan of the year.
INTERVAL_RANGE: ColumnClause[str] = literal_column("tstzrange(started_at, ended_at)")

# Lengths of the two coded columns; the CHECK constraints below are the real
# guard, these only keep a typo from filling a page.
CODE_LENGTH = 16
# Reverse-DNS identifiers of applications: `com.apple.dt.Xcode` and the like.
BUNDLE_ID_LENGTH = 255


def _in_list(column: str, values: tuple[str, ...]) -> str:
    """`column IN ('a', 'b')` built from the tuple the code reads, not retyped."""
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class WorkInterval(Base):
    """
    One stretch of the day recorded as work or as a pause.

    **Ручная запись и агентская лежат в одной таблице.** They differ by `source`
    and by nothing else, because "во сколько я начал" is one fact with two
    possible authors; two tables would mean two sums and a question about which
    of them the verdict was computed from.

    **Правка агентского интервала ничего не затирает.** Moving the boundaries of
    a row the agent wrote copies its original boundaries into
    `auto_started_at`/`auto_ended_at`, flips `source` to `corrected` and stamps
    `edited_at`. Without that, «исправил руками» and «агент так и посчитал»
    become indistinguishable and the number stops being evidence in either
    direction.

    **Заголовков окон здесь нет и не будет.** The privacy line of the whole day
    model runs through this table: an interval carries when, in which mode and —
    at most — which application (`app_bundle_id`). The text of a window title is
    the content of a chat, a document and a medical record at once, and a table
    that does not have the column cannot leak it. Screenshots do not exist
    anywhere in this system by construction.

    **Какому дню принадлежит интервал, решает `app.core.daytime.local_date`.**
    The day of the *start*: an interval from 23:00 to 01:00 belongs to the day it
    began on and is not cut in half. This module stores the answer, it does not
    compute it.
    """

    __tablename__ = "work_interval"
    __table_args__ = (
        # An interval that ends before it starts is not a short interval, it is a
        # typo. Refused by the database rather than by a validator, because the
        # agent, an import and a `psql` session all write here.
        CheckConstraint(
            "ended_at IS NULL OR ended_at > started_at",
            name="ck_work_interval_ends_after_start",
        ),
        CheckConstraint(_in_list("source", SOURCES), name="ck_work_interval_source"),
        CheckConstraint(_in_list("mode", MODES), name="ck_work_interval_mode"),
        # The day's intervals in the order a person reads them.
        Index("ix_work_interval_day_started", "day_date", "started_at"),
        Index("ix_work_interval_range", INTERVAL_RANGE, postgresql_using="gist"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )

    # The day of `started_at`, as `local_date()` reads it. Stored rather than
    # derived on read: the boundary hour is versioned canon, and a day already
    # written must not move because the canon changed afterwards.
    day_date: Mapped[date_type] = mapped_column(
        ForeignKey("day.date", ondelete="CASCADE")
    )

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # NULL means the interval is running right now — the state the floating
    # switch of the future agent leaves behind between two clicks.
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    source: Mapped[str] = mapped_column(String(CODE_LENGTH), server_default="manual")
    mode: Mapped[str] = mapped_column(String(CODE_LENGTH), server_default="work")

    # What the agent proposed before a person moved it. NULL on a row nobody
    # corrected — including every row a person typed in the first place.
    auto_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    auto_ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    app_bundle_id: Mapped[str | None] = mapped_column(
        String(BUNDLE_ID_LENGTH), nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # When a person intervened. NULL means nobody has, which is what separates a
    # number that was agreed with from one that was merely not looked at.
    edited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"<WorkInterval(day={self.day_date}, started_at={self.started_at}, "
            f"source='{self.source}')>"
        )
