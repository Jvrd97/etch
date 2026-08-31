# [review:need-review] PHASE-03/86, PHASE-03/137, PHASE-03/142
# summary: the day tables — versioned canon `day_rule_set` (no two intervals may overlap, enforced by a GiST exclusion constraint) and `day` with kind/is_nocode materialised at creation; since #142 the rule row also carries the map of the day — edges as times, the free evening, the evening with the family — the ceilings of the generator and the verdict formula
from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

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
    text,
)
from sqlalchemy.sql.elements import ColumnClause
from sqlalchemy.dialects.postgresql import ARRAY, ExcludeConstraint, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base
from app.models.anchor import DEFAULT_ANCHOR_CODES

# The half-open interval a rule row is in force on, as PostgreSQL spells it.
# `[)` is what makes a rule change a single date: the new row's `valid_from`
# equals the old row's `valid_to`, and the boundary date belongs to the new one.
RULE_INTERVAL: ColumnClause[str] = literal_column(
    "daterange(valid_from, valid_to, '[)')"
)

# Length of the `kind` value; the check constraint is the real guard.
KIND_LENGTH = 10

# Which kinds of plan item are allowed to call themselves `rigidity='hard'`.
# The edges of the day, and nothing else: an anchor of the canon, and a
# `hard_point`, which is *defined* as a commitment at a clock time. A task that
# wants to be immovable has to become an anchor first, in the open.
DEFAULT_HARD_EDGE_KINDS: tuple[str, ...] = ("anchor", "hard_point")

# The anchors a won day has to close, taken from the catalogue rather than
# retyped: since `#92` the kinds of anchor are rows of `anchor_kind`, and a
# second list here would be the copy that drifts. Composition is data precisely
# so that adding a seventh anchor is an INSERT rather than an edit of
# `app.day.evaluate`.
DEFAULT_ANCHORS: tuple[str, ...] = DEFAULT_ANCHOR_CODES

# The verdict formula: which conditions lower a day, in the order they are
# weighed. The order is the priority of `config.md` — здоровье > работа >
# отношения — and the codes are the ones `app.day.evaluate` answers with.
# Dropping a code here stops that condition from losing a day, without a line
# of Python changing.
DEFAULT_VERDICT_RULE: dict[str, Any] = {
    "reason_order": ["overtime", "anchors", "tasks"]
}

# Роли, акт одной из которых обязан закрыть рабочий день (`#137`). Строкой
# через запятую, а не массивом: список из двух кодов, и колонка читается на
# экране правил как есть. Коды — те же, что в `app.models.role`.
DEFAULT_ROLE_CLAUSE_ROLES = "cto,architect"

# Разделитель кодов в `role_clause_roles`. Назван, потому что его читают в двух
# местах: разбор строки и её сборка на экране правил.
ROLE_CLAUSE_SEPARATOR = ","


def role_clause_roles(raw: str) -> tuple[str, ...]:
    """
    Коды ролей клауза из строки колонки, без пустых и без повторов.

    Функция, а не `split` по месту: разбор нужен и вердикту, и экрану правил, а
    два разных разбора одной колонки разошлись бы на первом же пробеле после
    запятой.
    """
    seen: list[str] = []
    for part in raw.split(ROLE_CLAUSE_SEPARATOR):
        code = part.strip()
        if code and code not in seen:
            seen.append(code)
    return tuple(seen)


# ISO weekday numbers of the days off, kept apart from `workdays` because
# "не рабочий" and "выходной" are not the same statement: the generator plans
# study and music into a day off and plans nothing at all into a day that is
# merely not a workday.
DEFAULT_DAYS_OFF: tuple[int, ...] = (6, 7)


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

    # The wall of minutes past which a day is never *planned*, however the
    # exception ceiling is spent. `work_cap_min` judges a day that happened;
    # this one bounds a day being written (`#147`).
    overtime_lost_min: Mapped[int] = mapped_column(
        Integer, default=600, server_default="600"
    )

    max_work_tasks: Mapped[int] = mapped_column(SmallInteger, server_default="4")
    max_study_items: Mapped[int] = mapped_column(
        SmallInteger, default=2, server_default="2"
    )
    # Share of planned tasks that has to be closed for the day to be won.
    tasks_required_ratio: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), server_default="1.00"
    )
    overtime_disqualifies: Mapped[bool] = mapped_column(Boolean, server_default="true")

    # The hard edges of the day, as times rather than as prose. Until `#142`
    # «подъём 6:00, старт работы 7:45, ревью 15:40, отбой 22:30» lived only in
    # `config.md`, so a plan could not be checked against the map of the day and
    # a person could not see the map at all.
    wake_at: Mapped[time] = mapped_column(
        Time, default=time(6, 0), server_default="06:00"
    )
    work_start: Mapped[time] = mapped_column(
        Time, default=time(7, 45), server_default="07:45"
    )
    review_at: Mapped[time] = mapped_column(
        Time, default=time(15, 40), server_default="15:40"
    )
    bedtime_max: Mapped[time] = mapped_column(
        Time, default=time(22, 30), server_default="22:30"
    )

    # The block of the evening that is deliberately left unwritten. «Не
    # перезакручивать» is exactly this interval: the generator may put nothing
    # inside it, and that is checkable only because the two times are here.
    free_evening_start: Mapped[time] = mapped_column(
        Time, default=time(19, 10), server_default="19:10"
    )
    free_evening_end: Mapped[time] = mapped_column(
        Time, default=time(21, 0), server_default="21:00"
    )

    # The third priority of `config.md` as data. The flag is a column and not a
    # branch in the planner for the same reason the ceiling of hours is: a
    # requirement to the evening changes by a new row, not by an edit of code.
    relationship_anchor_required: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    relationship_evening_start: Mapped[time] = mapped_column(
        Time, default=time(18, 30), server_default="18:30"
    )
    relationship_evening_end: Mapped[time] = mapped_column(
        Time, default=time(21, 0), server_default="21:00"
    )

    # Which kinds of plan item may be `rigidity='hard'` — read by
    # `app.day.plan_validate` instead of a constant of its own.
    hard_edge_kinds: Mapped[list[str]] = mapped_column(
        JSONB,
        default=lambda: list(DEFAULT_HARD_EDGE_KINDS),
        server_default=text("""'["anchor", "hard_point"]'"""),
    )
    # The anchors a won day has to close, read by `app.day.evaluate`.
    anchors: Mapped[list[str]] = mapped_column(
        JSONB,
        default=lambda: list(DEFAULT_ANCHORS),
        server_default=text(
            """'["подъём", "спорт", "старт работы", "ревью", "отбой", "relationship"]'"""
        ),
    )
    # Клауз роли (`#137`): рабочий день, не закрывший ни одного акта роли,
    # отличной от тимлида, не выигран. Два поля строки правила, а не четвёртая
    # таблица правил: версионированный канон дня уже существует этой строкой, и
    # двух версионированных критериев в одной базе быть не должно.
    #
    # Доля времени в вердикт не входит намеренно: день из восьми часов ревью
    # стопроцентно тимлидский по минутам и может нести единственный
    # архитектурный акт, ради которого он и был. Доли идут в недельную сводку
    # (`#138`).
    role_clause_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    role_clause_roles: Mapped[str] = mapped_column(
        String(100),
        default=DEFAULT_ROLE_CLAUSE_ROLES,
        server_default=DEFAULT_ROLE_CLAUSE_ROLES,
    )

    # The verdict formula: which conditions lower a day, in which order.
    verdict_rule: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=lambda: dict(DEFAULT_VERDICT_RULE),
        server_default=text("""'{"reason_order": ["overtime", "anchors", "tasks"]}'"""),
    )

    # ISO weekday numbers, 1 = Monday .. 7 = Sunday — the same numbering
    # `date.isoweekday()` speaks, so nothing has to translate on the way in.
    workdays: Mapped[list[int]] = mapped_column(ARRAY(SmallInteger))
    nocode_days: Mapped[list[int]] = mapped_column(ARRAY(SmallInteger))
    # Not the complement of `workdays`: a day off is a day the canon fills with
    # study, lessons and music, and the generator has to tell it apart from a
    # day that simply is not a workday.
    days_off: Mapped[list[int]] = mapped_column(
        JSONB, default=lambda: list(DEFAULT_DAYS_OFF), server_default=text("'[6, 7]'")
    )

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
