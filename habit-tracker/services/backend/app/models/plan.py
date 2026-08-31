# [review:need-review] PHASE-03/87, PHASE-03/93, PHASE-03/110, PHASE-03/130
# summary: the plan tables — `day_plan` (one per day), `plan_section` (ordered), `plan_item` (ordered, nestable) with the four CHECKs that turn the prose rules of config.md into constraints the database enforces; #93 gives both `quarter_goal_id` columns their foreign key; #110 adds who last touched a line and when, and makes a position unique inside its level so a reorder cannot leave holes or twins
from __future__ import annotations

import uuid
from datetime import date as date_type
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSTZRANGE, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import event
from sqlalchemy.sql import func

from app.core.database import Base

# The generated columns, spelled once so the model, the migration and the tests
# cannot drift. `tstzrange` and a two-argument `to_tsvector` are both immutable,
# which is what lets postgres store them rather than recompute them per row read.
WINDOW_EXPR = "tstzrange(starts_at, ends_at)"
SEARCH_EXPR = "to_tsvector('russian', text_plain)"

# The kinds a section can be. Not a CHECK: the vocabulary of sections is a
# guess that the import of live plans (`#89`) is expected to widen, and a
# rejected import teaches nothing while an unknown value in a column can be
# read and counted.
SECTION_KINDS: tuple[str, ...] = (
    "anchors",
    "training",
    "hard_points",
    "work",
    "study",
    "evening",
    "personal",
    "queue",
    "free",
    "other",
)

# The kinds an item can be. A CHECK here, because these five drive the
# constraints below: `task` is what the ceiling counts and what needs a window,
# `minimum` is a child with its own mark, `anchor` and `hard_point` are the
# edges of the day.
ITEM_KINDS: tuple[str, ...] = (
    "bullet",
    "step",
    "table_row",
    "task",
    "anchor",
    "hard_point",
    "minimum",
)

RIGIDITY_VALUES: tuple[str, ...] = ("hard", "soft", "free")

PLAN_STATUSES: tuple[str, ...] = ("draft", "active", "closed")

# Кто последним трогал строку плана. Три значения, а не булев «человек ли»:
# правка скиллом `/day-open` и правка агентом — разные источники, и различать
# их придётся раньше, чем появится желание завести четвёртое значение.
EDITED_BY_HUMAN = "human"
EDITED_BY_AI = "ai"
EDITED_BY_SKILL = "skill"
EDITORS: tuple[str, ...] = (EDITED_BY_HUMAN, EDITED_BY_AI, EDITED_BY_SKILL)

# Позиция уникальна внутри уровня, а уровень — это `(section_id, parent_id)`:
# `ord` нумерует братьев между собой, поэтому родитель на позиции 0 и его
# ребёнок на позиции 0 в одной секции законны, а уникальность по
# `(section_id, ord)` была бы ложной.
#
# Пишется DDL-строкой, а не `UniqueConstraint`: `NULLS NOT DISTINCT` (без него
# правило не действует для корневых пунктов, у которых `parent_id` пуст) в
# SQLAlchemy 2.0.23 ещё не выражается, а `DEFERRABLE` обязателен — перестановка
# проходит через промежуточное состояние с дублями и должна падать только на
# коммите. Дословный близнец живёт в ревизии `b2d4f6a8c0e3`.
POSITION_UNIQUE_NAME = "uq_plan_item_position"
POSITION_UNIQUE_DDL = (
    f"ALTER TABLE plan_item ADD CONSTRAINT {POSITION_UNIQUE_NAME} "
    "UNIQUE NULLS NOT DISTINCT (section_id, parent_id, ord) "
    "DEFERRABLE INITIALLY DEFERRED"
)
PLAN_SOURCES: tuple[str, ...] = ("day-open", "import", "manual")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    """`kind IN ('a', 'b')` — spelled once for the model and the migration."""
    joined = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({joined})"


class DayPlan(Base):
    """
    The plan of one day, as a whole document.

    One row per day, enforced by the unique foreign key rather than by whoever
    writes: a plan arrives from `/day-open` in one piece and replaces the
    previous one in one transaction, so a second plan on the same date is never
    a legitimate state to be in.

    `raw_md` keeps the markdown the plan was born as. Nothing reads it in
    normal operation — it exists because the migration off files is one-way, and
    the first months of rows will be read back by a human wondering whether the
    parse lost something.
    """

    __tablename__ = "day_plan"
    __table_args__ = (
        CheckConstraint(_in_list("status", PLAN_STATUSES), name="ck_day_plan_status"),
        CheckConstraint(_in_list("source", PLAN_SOURCES), name="ck_day_plan_source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Unique, so the day owns at most one plan; the FK ties it to a `day` row
    # that already carries the rule the plan is validated against.
    day_date: Mapped[date_type] = mapped_column(
        "day_date", Date, ForeignKey("day.date", ondelete="CASCADE"), unique=True
    )

    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The one word the title is marked with — "*без работы*" in the live plans.
    title_marker: Mapped[str | None] = mapped_column(Text, nullable=True)
    lede: Mapped[str | None] = mapped_column(Text, nullable=True)
    purpose_md: Mapped[str | None] = mapped_column(Text, nullable=True)

    # «Ради чего сегодня» — the goal of the quarter the whole day is spent on
    # (`goal.md`, уровень 5). `RESTRICT`, like the one on `plan_item`: deleting a
    # goal a day was lived for has to fail loudly.
    quarter_goal_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "quarter_goal.id",
            ondelete="RESTRICT",
            name="fk_day_plan_quarter_goal_id",
        ),
        nullable=True,
    )

    counters: Mapped[list[Any]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    condition_tomorrow: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(16), server_default="active")
    source: Mapped[str] = mapped_column(String(16), server_default="day-open")

    raw_md: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    sections: Mapped[list[PlanSection]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="PlanSection.ord",
    )

    def __repr__(self) -> str:
        return f"<DayPlan(day_date={self.day_date}, status='{self.status}')>"


class PlanSection(Base):
    """
    One section of a plan, in the order the plan was written.

    `ord` is assigned by the server from the position in the incoming document,
    never by the client: the acceptance case is "the order matches the one
    sent", and a client-supplied number is one typo away from two sections
    claiming the same place.
    """

    __tablename__ = "plan_section"
    __table_args__ = (
        UniqueConstraint("plan_id", "ord", name="uq_plan_section_plan_ord"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("day_plan.id", ondelete="CASCADE")
    )

    ord: Mapped[int] = mapped_column(SmallInteger)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(String(16))

    plan: Mapped[DayPlan] = relationship(back_populates="sections")
    items: Mapped[list[PlanItem]] = relationship(
        back_populates="section",
        cascade="all, delete-orphan",
        order_by="PlanItem.ord",
    )

    def __repr__(self) -> str:
        return f"<PlanSection(ord={self.ord}, kind='{self.kind}')>"


class PlanItem(Base):
    """
    One line of a plan — and where the prose of `config.md` becomes a constraint.

    Four CHECKs carry rules that until now lived as sentences an agent either
    remembered or did not:

    * a task has a window and a criterion of being done (the canon of
      2026-08-28) — a task without either is not a task, it is a wish;
    * a `free` item has no window at all, which is what makes the free evening
      block physically impossible to fill with a schedule ("не перезакручивать");
    * a task names either a quarter goal or the reason it is not tied to one, so
      that somebody else's urgency cannot be written in silently;
    * a window ends after it starts, once midnight-crossing has been unrolled
      into `+24h` by the service.

    The bar on the *number* of tasks is deliberately not here. It belongs to the
    rule row, applies to a plan as a whole, and a row-level trigger would refuse
    the import of the historic days that broke it — which are exactly the days
    worth keeping.

    `window` and `search` are generated columns rather than service-side writes:
    an overlap of two windows is then a self-join on `&&` over a GiST index
    instead of a recomputation on every render, and full-text search over the
    plan needs no second write path to fall out of step.
    """

    __tablename__ = "plan_item"
    __table_args__ = (
        CheckConstraint(_in_list("kind", ITEM_KINDS), name="ck_plan_item_kind"),
        CheckConstraint(_in_list("edited_by", EDITORS), name="ck_plan_item_edited_by"),
        CheckConstraint(
            _in_list("rigidity", RIGIDITY_VALUES), name="ck_plan_item_rigidity"
        ),
        CheckConstraint(
            "kind <> 'task' OR (starts_at IS NOT NULL AND ends_at IS NOT NULL "
            "AND done_criterion IS NOT NULL)",
            name="ck_plan_item_task_has_window_and_criterion",
        ),
        CheckConstraint(
            "rigidity <> 'free' OR starts_at IS NULL",
            name="ck_plan_item_free_has_no_window",
        ),
        CheckConstraint(
            "kind <> 'task' OR quarter_goal_id IS NOT NULL "
            "OR unlinked_reason IS NOT NULL",
            name="ck_plan_item_task_is_linked_or_explained",
        ),
        CheckConstraint(
            "starts_at IS NULL OR ends_at > starts_at",
            name="ck_plan_item_window_is_forward",
        ),
        Index("ix_plan_item_section_ord", "section_id", "ord"),
        Index("ix_plan_item_window", "window", postgresql_using="gist"),
        Index("ix_plan_item_search", "search", postgresql_using="gin"),
        Index("ix_plan_item_carried_from", "carried_from_item_id"),
        Index(
            "ix_plan_item_quick_mark_id",
            "quick_mark_id",
            postgresql_where=text("quick_mark_id IS NOT NULL"),
        ),
        # Partial: most items carry no code, and NULLs would otherwise make the
        # constraint vacuous for exactly the rows that need no protection.
        Index(
            "uq_plan_item_section_code",
            "section_id",
            "code",
            unique=True,
            postgresql_where=text("code IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    section_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plan_section.id", ondelete="CASCADE")
    )
    # A child of another item: the `Минимум` of a training block, a step of a
    # numbered list. Nested so the minimum gets its own mark — 29 August proved
    # that a minimum declared inside a task and without its own tick is not done.
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("plan_item.id", ondelete="CASCADE"),
        nullable=True,
    )
    ord: Mapped[int] = mapped_column(SmallInteger)

    kind: Mapped[str] = mapped_column(String(16))
    rigidity: Mapped[str] = mapped_column(String(8), server_default="soft")

    text_md: Mapped[str] = mapped_column(Text)
    # Derived from `text_md` by the service, not by the database: stripping
    # markdown is not an immutable SQL expression, and `search` needs a plain
    # column to generate from.
    text_plain: Mapped[str] = mapped_column(Text)

    starts_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # "пока ногти", "если проснусь" — the tail of `Окно ::` that is not a time.
    window_comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    # `W1`, `подъём` — the short handle a human and an error message use to
    # point at this line.
    code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    done_criterion: Mapped[str | None] = mapped_column(Text, nullable=True)
    why_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan_md: Mapped[str | None] = mapped_column(Text, nullable=True)

    external_ref: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Every other `Подпись :: значение` the plans use — `Факт`, `Формат`, `Вход`,
    # `Материал`. Fifteen-odd labels appear in the live plans and six earned a
    # column; the rest arrive here whole rather than being dropped for lacking one.
    extra: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )

    # `RESTRICT` rather than `SET NULL`: a task that named a goal of the quarter
    # must not quietly become somebody else's urgency because the goal was
    # deleted. The delete is what fails, and a person decides what the task was.
    quarter_goal_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "quarter_goal.id",
            ondelete="RESTRICT",
            name="fk_plan_item_quarter_goal_id",
        ),
        nullable=True,
    )
    unlinked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Кнопка справочника, которой этот пункт отмечается (#130). Ссылка идёт
    # отсюда, а не из `quick_marks`: план — событие одного дня, кнопка живёт
    # месяцами. `SET NULL`, потому что кнопку удаляют, а прожитый день остаётся,
    # и пункт без кнопки — это обычный пункт, отмечаемый руками.
    quick_mark_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "quick_marks.id",
            ondelete="SET NULL",
            name="fk_plan_item_quick_mark_id",
        ),
        nullable=True,
    )

    carried_from_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("plan_item.id", ondelete="SET NULL"),
        nullable=True,
    )
    carry_count: Mapped[int] = mapped_column(SmallInteger, server_default="0")

    # The positional key a legacy `<script id="plan-state">` block used, kept so
    # the import (`#89`) can attach an old mark to the item it belonged to.
    legacy_key: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Generated and stored by postgres. Null exactly when there is no window,
    # which is what makes "has a window" a range test rather than a pair of
    # null checks two callers would spell differently.
    window: Mapped[Any] = mapped_column(
        "window", TSTZRANGE, Computed(WINDOW_EXPR, persisted=True), nullable=True
    )
    search: Mapped[Any] = mapped_column(
        TSVECTOR, Computed(SEARCH_EXPR, persisted=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Ставится сервисом на каждой правке, а не триггером: правка через `#110`
    # проходит одним местом, и триггер здесь был бы вторым автором того же
    # значения — тем самым дублем, от которого проект уходит.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    edited_by: Mapped[str] = mapped_column(String(8), server_default=EDITED_BY_AI)

    section: Mapped[PlanSection] = relationship(back_populates="items")
    children: Mapped[list[PlanItem]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
        order_by="PlanItem.ord",
        foreign_keys=[parent_id],
    )
    parent: Mapped[PlanItem | None] = relationship(
        back_populates="children",
        remote_side=[id],
        foreign_keys=[parent_id],
    )

    def __repr__(self) -> str:
        return f"<PlanItem(kind='{self.kind}', ord={self.ord}, code={self.code!r})>"


# Ограничение вешается после создания таблицы, а не в `__table_args__`: так один
# и тот же DDL достаётся и рабочей базе (через ревизию), и тестовой, которую
# `create_all` собирает из метаданных, минуя Alembic.
def _add_position_constraint(
    target: Any,
    connection: Any,
    **kw: Any,  # noqa: ANN401 - подпись события SQLAlchemy
) -> None:
    """Повесить `uq_plan_item_position` сразу после создания таблицы."""
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql(POSITION_UNIQUE_DDL)


event.listen(PlanItem.__table__, "after_create", _add_position_constraint)
