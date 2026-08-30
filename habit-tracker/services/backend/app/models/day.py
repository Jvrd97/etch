# [review:need-review] PHASE-03/86
# summary: the day tables — versioned canon `day_rule_set` (no two intervals may overlap, enforced by a GiST exclusion constraint) and `day` with kind/is_nocode materialised at creation
from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    Time,
    literal_column,
)
from sqlalchemy.sql.elements import ColumnClause
from sqlalchemy.dialects.postgresql import ARRAY, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base

# The half-open interval a rule row is in force on, as PostgreSQL spells it.
# `[)` is what makes a rule change a single date: the new row's `valid_from`
# equals the old row's `valid_to`, and the boundary date belongs to the new one.
RULE_INTERVAL: ColumnClause[str] = literal_column(
    "daterange(valid_from, valid_to, '[)')"
)

# Length of the `kind` value; the check constraint is the real guard.
KIND_LENGTH = 10


class DayRuleSet(Base):
    """
    The canon of a day, in force over an interval of dates.

    The ceiling on work, the stop time, the task bar, the mandatory anchors, the
    timezone and the hour a day starts at are a row here rather than constants in
    a module because the canon has already changed twice in a month. With numbers
    in code the next edit rewrites the verdict of every past day and there is
    nothing left to explain why the 14th was judged differently; with a row, a
    change of canon is an `INSERT` and yesterday keeps the rule it was lived
    under.

    Overlapping intervals are refused by the database, not by a service: two rules
    in force on one date make "which rule applies" a coin toss, and a service
    check is skipped by any writer that does not go through it — an import, a
    migration, a `psql` session.
    """

    __tablename__ = "day_rule_set"
    __table_args__ = (
        # `ExcludeConstraint` carries no annotations in SQLAlchemy 2.0, so
        # --strict calls it untyped; there is no typed way to declare an
        # exclusion constraint and the alternative is raw DDL in a listener.
        ExcludeConstraint(  # type: ignore[no-untyped-call]
            (RULE_INTERVAL, "&&"),
            name="excl_day_rule_set_no_overlap",
            using="gist",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    valid_from: Mapped[date] = mapped_column(Date)
    # NULL means "still in force"; by construction at most one row can have it.
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    # The day boundary. `app.core.daytime` reads these two and nothing else
    # decides which day a moment belongs to.
    timezone: Mapped[str] = mapped_column(String(64), server_default="Europe/Berlin")
    day_start_hour: Mapped[int] = mapped_column(SmallInteger, server_default="4")

    # Work: the everyday ceiling, the exception ceiling, and the wall the day
    # stops at regardless of how the minutes add up.
    work_cap_min: Mapped[int] = mapped_column(Integer, server_default="480")
    work_hard_cap_min: Mapped[int] = mapped_column(Integer, server_default="540")
    work_stop_at: Mapped[time] = mapped_column(Time, server_default="16:00")

    max_work_tasks: Mapped[int] = mapped_column(SmallInteger, server_default="4")
    # Share of planned tasks that has to be closed for the day to be won.
    tasks_required_ratio: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), server_default="1.00"
    )
    overtime_disqualifies: Mapped[bool] = mapped_column(Boolean, server_default="true")

    # ISO weekday numbers, 1 = Monday .. 7 = Sunday — the same numbering
    # `date.isoweekday()` speaks, so nothing has to translate on the way in.
    workdays: Mapped[list[int]] = mapped_column(ARRAY(SmallInteger))
    nocode_days: Mapped[list[int]] = mapped_column(ARRAY(SmallInteger))

    required_anchors: Mapped[list[str]] = mapped_column(ARRAY(Text))
    note_md: Mapped[str] = mapped_column(Text, server_default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    days: Mapped[list[Day]] = relationship(back_populates="rule_set")

    def __repr__(self) -> str:
        return (
            f"<DayRuleSet(id={self.id}, valid_from={self.valid_from}, "
            f"valid_to={self.valid_to})>"
        )


class Day(Base):
    """
    One day of one life, keyed by its local date.

    `kind` and `is_nocode` are stored, not derived on read. The week schedule has
    already been edited once, and a derived answer would quietly re-label every
    past Tuesday the moment it is edited again: last Tuesday has to stay what it
    was. They are materialised from the rule that was in force the day the row
    was created.

    `opened_at` is NULL until someone actually opens the day. That is what makes
    "nobody came" a different fact from "came and did nothing", which the file
    system this replaces could not tell apart.
    """

    __tablename__ = "day"
    __table_args__ = (
        CheckConstraint("kind IN ('work', 'off')", name="ck_day_kind"),
        # Named by hand: SQLAlchemy's default for `day.rule_set_id` would be
        # `ix_day_rule_set_id`, which is already the name of the index on
        # `day_rule_set.id`. Index names are database-wide in postgres, so the
        # two would collide on create_all.
        Index("ix_day_rule_set_id_fk", "rule_set_id"),
    )

    # The attribute is not called `date`: the class body would then shadow the
    # `datetime.date` its own annotations are resolved against. Same trick as
    # `HealthHourBucket.min_value`.
    day_date: Mapped[date] = mapped_column("date", Date, primary_key=True)

    rule_set_id: Mapped[int] = mapped_column(ForeignKey("day_rule_set.id"))

    kind: Mapped[str] = mapped_column(String(KIND_LENGTH))
    is_nocode: Mapped[bool] = mapped_column(Boolean)

    opened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_touched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    rule_set: Mapped[DayRuleSet] = relationship(back_populates="days")

    def __repr__(self) -> str:
        return f"<Day(date={self.day_date}, kind='{self.kind}')>"
