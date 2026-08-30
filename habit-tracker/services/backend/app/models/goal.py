# [review:need-review] PHASE-03/93
# summary: the goal tables — `goal_level` (0..5, the open questions of goal.md kept as questions), `milestone` (M1-M10 with the criterion of being done), `milestone_dep` (the «Открывается чем» column as a graph) and `quarter_goal`, whose CHECK on `ord` and UNIQUE on (quarter, ord) make «ровно пять задач на квартал» a fact of the schema
from __future__ import annotations

from datetime import date as date_type

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.checks import in_list

# The four states a milestone of `goal.md` can be in. A CHECK, unlike the
# vocabulary of section kinds: these four are read by the screen, and a fifth
# spelling would show up as a milestone in no state at all.
MILESTONE_STATUSES: tuple[str, ...] = ("open", "in-progress", "done", "dropped")
MILESTONE_STATUS_OPEN = "open"
MILESTONE_STATUS_DONE = "done"

# Levels 0 to 5 of `goal.md`: the end point, the role, the year, the milestones,
# the quarter, the day. Six, and the file is built on there being six.
GOAL_LEVEL_MIN = 0
GOAL_LEVEL_MAX = 5

# «Больше пяти — цель размазана» (goal.md, уровень 4). The bar is a CHECK plus a
# UNIQUE rather than a service check: a sixth goal has to be refused for an
# import and a `psql` session too, and the ceiling only holds when the positions
# are also distinct.
QUARTER_GOAL_MIN_ORD = 1
QUARTER_GOAL_MAX_ORD = 5

# The three states a goal of the quarter can be in, with the same CHECK a
# milestone's status has. Three rather than four: `in-progress` says nothing
# about a goal that runs for a whole quarter — every one of the five is in
# progress the day it is written — while `dropped` is a real outcome and
# «квартал закончился, цель не сделана» has to stay distinguishable from it.
QUARTER_GOAL_STATUSES: tuple[str, ...] = ("open", "done", "dropped")
QUARTER_GOAL_STATUS_OPEN = "open"


class GoalLevel(Base):
    """
    One `## Уровень N` of `goal.md`.

    Keyed by the level itself rather than by a surrogate id: the file has
    exactly one block per level and the number is what both the file and the
    screen order by, so a second row for level 2 is not a state worth being able
    to reach.

    `open_questions` keeps the `⚠ подтверди` lines as questions. Folding them
    into `body_md` would make them prose again, and the whole point of the mark
    in the file is that these are the sentences the author has not confirmed.
    """

    __tablename__ = "goal_level"
    __table_args__ = (
        CheckConstraint(
            f"level BETWEEN {GOAL_LEVEL_MIN} AND {GOAL_LEVEL_MAX}",
            name="ck_goal_level_level",
        ),
    )

    level: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    body_md: Mapped[str] = mapped_column(Text, server_default="")
    open_questions: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default="{}"
    )

    def __repr__(self) -> str:
        return f"<GoalLevel(level={self.level}, title={self.title!r})>"


class Milestone(Base):
    """
    One row of the milestone table of `goal.md` — `M1`…`M10`.

    The code is the primary key because it is what everything else names: the
    quarter goal that carries a milestone, the dependency graph, and the person
    saying "M9 закрыт". A surrogate id would add a number nobody would ever use.

    `status` and `done_on` are the only two columns the import does not own.
    Whether a milestone is done is a fact a person establishes, and `goal.md`
    does not record it: re-reading the file must not un-tick M2.
    """

    __tablename__ = "milestone"
    __table_args__ = (
        CheckConstraint(
            in_list("status", MILESTONE_STATUSES), name="ck_milestone_status"
        ),
    )

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    done_criterion: Mapped[str | None] = mapped_column(Text, nullable=True)
    # «сейчас», «после M2+M3», «~2032, тебе 32» — a when that is an orientation
    # rather than a date. Stored as the text it is: `goal.md` says outright that
    # the dates are landmarks, not promises, and a `date` column would turn one
    # into the other.
    when_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ord: Mapped[int] = mapped_column(SmallInteger)

    status: Mapped[str] = mapped_column(
        String(16), server_default=MILESTONE_STATUS_OPEN
    )
    done_on: Mapped[date_type | None] = mapped_column(nullable=True)

    def __repr__(self) -> str:
        return f"<Milestone(code={self.code!r}, status={self.status!r})>"


class MilestoneDep(Base):
    """
    One edge of «Открывается чем»: `milestone_code` waits for `depends_on_code`.

    A table rather than a column, because M10 waits for two things at once. As
    prose the answer to "что закрыто раньше M10" is a cell to read by eye; as
    rows it is a query.
    """

    __tablename__ = "milestone_dep"

    milestone_code: Mapped[str] = mapped_column(
        String(16), ForeignKey("milestone.code", ondelete="CASCADE"), primary_key=True
    )
    depends_on_code: Mapped[str] = mapped_column(
        String(16), ForeignKey("milestone.code", ondelete="CASCADE"), primary_key=True
    )

    def __repr__(self) -> str:
        return f"<MilestoneDep({self.milestone_code!r} <- {self.depends_on_code!r})>"


class QuarterGoal(Base):
    """
    One of the five goals of a quarter — and the row a task of a plan points at.

    Two constraints carry the rule of `goal.md`: `ord` is between one and five,
    and a position is taken once per quarter. Either alone is not the ceiling —
    a CHECK lets five rows all claim position 3, and a UNIQUE alone lets a sixth
    goal call itself number 6. Together they make the sixth goal impossible to
    write, which is the acceptance case: the ceiling is refused by the database,
    not by whoever happened to call the service.

    `quarter` is `'2026-Q3'` — sortable, and the shape already used by
    `week.iso_code` (`'2026-W35'`). `goal.md` writes it as «Q3 2026»; the import
    normalises it once rather than every reader parsing both.
    """

    __tablename__ = "quarter_goal"
    __table_args__ = (
        CheckConstraint(
            f"ord BETWEEN {QUARTER_GOAL_MIN_ORD} AND {QUARTER_GOAL_MAX_ORD}",
            name="ck_quarter_goal_ord",
        ),
        UniqueConstraint("quarter", "ord", name="uq_quarter_goal_quarter_ord"),
        CheckConstraint(
            in_list("status", QUARTER_GOAL_STATUSES), name="ck_quarter_goal_status"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quarter: Mapped[str] = mapped_column(String(16))
    ord: Mapped[int] = mapped_column(SmallInteger)
    text_md: Mapped[str] = mapped_column(Text)
    # The milestone this goal of the quarter is a step of, when it is one: «M1 —
    # переезд» is both. Nullable, because «денежный контур работает end-to-end»
    # is a goal of the quarter and no milestone at all.
    milestone_code: Mapped[str | None] = mapped_column(
        String(16), ForeignKey("milestone.code", ondelete="SET NULL"), nullable=True
    )
    # Owned by a person, like `Milestone.status`: `goal.md` records no such
    # thing, so the import never writes it and re-reading the file cannot reopen
    # a goal that was closed.
    status: Mapped[str] = mapped_column(
        String(16), server_default=QUARTER_GOAL_STATUS_OPEN
    )

    def __repr__(self) -> str:
        return f"<QuarterGoal(quarter={self.quarter!r}, ord={self.ord})>"
