# [review:need-review] PHASE-03/134
# summary: the four role tables — `role` (the directory, with the target share kept as a hypothesis), `role_rule` (markup as rows, smaller priority wins), `role_time_block` (minutes: where the day went, CHECK minutes > 0) and `role_act` (acts: whether the role happened at all), both fact tables idempotent on the partial unique `(source, external_ref)`
from __future__ import annotations

from datetime import date as date_type
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base

# The four roles the directory is seeded with. Codes, not titles: the title is
# what a screen prints and a person may rewrite, the code is what a rule, a
# minute and an act all point at.
ROLE_CODE_CTO = "cto"
ROLE_CODE_ARCHITECT = "architect"
ROLE_CODE_TECHLEAD = "techlead"
ROLE_CODE_UNASSIGNED = "unassigned"

# Work that could not be attributed lands here rather than on NULL: «не удалось
# отнести» is a fact worth seeing on the screen, and a missing row is not.
ROLE_CODE_FALLBACK = ROLE_CODE_UNASSIGNED

# Where a minute or an act came from, **in order of precedence**: a manual
# record outranks a plan, a plan outranks ClickUp, and app usage is the weakest
# claim of all. The order is not decoration — it is the reason the `confirmed`
# guard in `app.crud.role` exists, since the only automatic writer of these rows
# is an importer and the only writer that may overrule it is a person.
SOURCE_MANUAL = "manual"
SOURCE_PLAN = "plan"
SOURCE_CLICKUP = "clickup"
SOURCE_GIT = "git"
SOURCE_APP_USAGE = "app_usage"
SOURCE_SIGNAL = "signal"

ROLE_TIME_SOURCES: tuple[str, ...] = (
    SOURCE_MANUAL,
    SOURCE_PLAN,
    SOURCE_CLICKUP,
    SOURCE_GIT,
    SOURCE_APP_USAGE,
)
# An act has no app-usage source — a window in focus is not an act — and gains
# `signal` instead.
ROLE_ACT_SOURCES: tuple[str, ...] = (
    SOURCE_MANUAL,
    SOURCE_PLAN,
    SOURCE_CLICKUP,
    SOURCE_GIT,
    SOURCE_SIGNAL,
)

# How sure the row is. `auto` is whatever an importer computed; `confirmed` is a
# person's word, and an importer never overwrites it.
CONFIDENCE_AUTO = "auto"
CONFIDENCE_CONFIRMED = "confirmed"
ROLE_CONFIDENCES: tuple[str, ...] = (CONFIDENCE_AUTO, CONFIDENCE_CONFIRMED)

# What a rule looks at. Plain strings, like every other enumerable field here:
# the taxonomy is personal and changes monthly, and a vocabulary that costs a
# migration is a vocabulary nobody edits.
MATCHER_BUNDLE_ID = "bundle_id"
MATCHER_WINDOW_TITLE_REGEX = "window_title_regex"
MATCHER_REPO_PATH_GLOB = "repo_path_glob"
MATCHER_COMMIT_PREFIX = "commit_prefix"
MATCHER_CLICKUP_LIST = "clickup_list"
MATCHER_CLICKUP_TAG = "clickup_tag"
MATCHER_PLAN_SECTION = "plan_section"
MATCHER_KINDS: tuple[str, ...] = (
    MATCHER_BUNDLE_ID,
    MATCHER_WINDOW_TITLE_REGEX,
    MATCHER_REPO_PATH_GLOB,
    MATCHER_COMMIT_PREFIX,
    MATCHER_CLICKUP_LIST,
    MATCHER_CLICKUP_TAG,
    MATCHER_PLAN_SECTION,
)

# Smaller wins. The default sits in the middle so that a rule written later can
# be made stronger *or* weaker without renumbering the ones already there.
RULE_PRIORITY_DEFAULT = 100


class Role(Base):
    """
    One role the working day can be spent in.

    A table rather than a PG enum, and the project has already paid for the
    difference: widening `fieldtype` cost a migration with `autocommit_block()`,
    while the health catalogue — deliberately a table — grows by inserts. The
    same reasoning applies twice over here, because the role is a foreign key
    from three other tables at once.

    `target_share_pct` is a **hypothesis**, in exactly the sense the 6:00 wake-up
    in `config.md` is one: it is what the quarter is aiming at, not what the day
    is judged by. Nothing in this module compares a measurement against it; the
    screen that prints it says out loud which of the two it is.
    """

    __tablename__ = "role"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    target_share_pct: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    # False for `unassigned`-like rows that exist to be counted, not to be aimed
    # at: non-working time produces no rows at all, so this is about which roles
    # a share is meaningful for.
    is_work: Mapped[bool] = mapped_column(Boolean, server_default="true")
    ord: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    rules: Mapped[list[RoleRule]] = relationship(back_populates="role")

    def __repr__(self) -> str:
        return f"<Role(id={self.id}, code='{self.code}')>"


class RoleRule(Base):
    """
    One line of the markup: «this pattern from this source means that role».

    Rows rather than a dictionary in Python, because the taxonomy is personal
    and changes monthly — and a taxonomy that changes by deploy does not change.

    Two rules can match the same sample; the smaller `priority` wins, and ties
    are broken by `id` so that the answer is a fact rather than a race (see
    `app.roles.matcher`). The foreign key is `RESTRICT`: deleting a role out from
    under the rules that name it would silently turn markup into `unassigned`.
    """

    __tablename__ = "role_rule"
    __table_args__ = (
        # The read pattern of the resolver: every active rule of one source,
        # already in the order the winner is picked by.
        Index("ix_role_rule_source_priority", "source", "priority"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    role_id: Mapped[int] = mapped_column(
        ForeignKey("role.id", ondelete="RESTRICT"), index=True
    )

    source: Mapped[str] = mapped_column(String(20))
    matcher_kind: Mapped[str] = mapped_column(String(30))
    pattern: Mapped[str] = mapped_column(String(500))
    priority: Mapped[int] = mapped_column(
        Integer, server_default=str(RULE_PRIORITY_DEFAULT)
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    role: Mapped[Role] = relationship(back_populates="rules")

    def __repr__(self) -> str:
        return (
            f"<RoleRule(id={self.id}, source='{self.source}', "
            f"kind='{self.matcher_kind}', priority={self.priority})>"
        )


class RoleTimeBlock(Base):
    """
    Minutes: the answer to «куда ушёл день».

    `started_at`/`ended_at` are nullable because the first and most important
    writer is a person typing «полтора часа на найм» — an interval nobody
    recorded the ends of. `minutes` is the measurement; the timestamps are
    context an importer can supply and a human usually cannot.

    Idempotency lives on the partial unique `(source, external_ref)`: a commit
    sha or a task id re-sent by an importer lands on the row it already wrote
    instead of adding a second one, so the day's total does not drift upward
    every time the importer runs. Rows with no `external_ref` — the manual ones —
    are outside that constraint, because two honest records of ninety minutes on
    hiring are two records and not a duplicate.
    """

    __tablename__ = "role_time_block"
    __table_args__ = (
        # Refusing zero belongs to the database rather than to a service: an
        # import, a `psql` session and a future writer all have to be refused,
        # and only the table is present in all three.
        CheckConstraint("minutes > 0", name="ck_role_time_block_minutes_positive"),
        Index(
            "ix_role_time_block_external",
            "source",
            "external_ref",
            unique=True,
            postgresql_where=text("external_ref IS NOT NULL"),
        ),
        Index("ix_role_time_block_day_role", "work_day", "role_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # The day the minutes are charged to. A date, not a moment: which day a
    # moment belongs to is `app.core.daytime.local_date`'s question alone, and
    # the manual form answers it by simply carrying the date.
    work_day: Mapped[date_type] = mapped_column(Date, index=True)
    role_id: Mapped[int] = mapped_column(
        ForeignKey("role.id", ondelete="RESTRICT"), index=True
    )

    source: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    minutes: Mapped[int] = mapped_column(Integer)
    confidence: Mapped[str] = mapped_column(String(10), server_default=CONFIDENCE_AUTO)
    external_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # `SET NULL`, unlike the role: losing the rule that produced a block is not a
    # reason to lose the block, and the minutes stay charged to the role they
    # were charged to.
    rule_id: Mapped[int | None] = mapped_column(
        ForeignKey("role_rule.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    role: Mapped[Role] = relationship()

    def __repr__(self) -> str:
        return (
            f"<RoleTimeBlock(id={self.id}, day={self.work_day}, "
            f"role_id={self.role_id}, minutes={self.minutes})>"
        )


class RoleAct(Base):
    """
    Acts: the answer to «роль сегодня вообще случилась».

    Not reducible to the minutes and not replaceable by them. A budget decision
    is fifteen minutes that turn a quarter; eight hours of code review is a
    hundred-percent tech-lead day by minutes and may still carry the single
    architectural act it existed for. The share would call that day a lie, and
    the act count alone would hide the week where architecture got forty minutes
    out of forty hours — so both are measured, separately.

    `act_kind` is a plain string for the same reason as everything else here;
    its vocabulary lives in `app.schemas.role` and grows by editing a schema.
    """

    __tablename__ = "role_act"
    __table_args__ = (
        Index(
            "ix_role_act_external",
            "source",
            "external_ref",
            unique=True,
            postgresql_where=text("external_ref IS NOT NULL"),
        ),
        Index("ix_role_act_day_role", "work_day", "role_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    work_day: Mapped[date_type] = mapped_column(Date, index=True)
    role_id: Mapped[int] = mapped_column(
        ForeignKey("role.id", ondelete="RESTRICT"), index=True
    )

    act_kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(20))
    external_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    confidence: Mapped[str] = mapped_column(String(10), server_default=CONFIDENCE_AUTO)
    occurred_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    role: Mapped[Role] = relationship()

    def __repr__(self) -> str:
        return (
            f"<RoleAct(id={self.id}, day={self.work_day}, "
            f"role_id={self.role_id}, kind='{self.act_kind}')>"
        )
