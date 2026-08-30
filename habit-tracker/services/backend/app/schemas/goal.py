# [review:need-review] PHASE-03/93
# summary: wire types of the goals — levels with their open questions, milestones carrying «Открывается чем» as a list of codes rather than as prose, and the five goals of a quarter sent as one set because the ceiling of five is a property of the set
"""
Wire types of `goal.md`.

**Зависимости приезжают списком кодов, а не текстом.** The file writes
«Открывается чем» as a sentence, and the whole reason `milestone_dep` exists is
that «M9 + M8» is two answers. The screen gets `["M8", "M9"]` and draws two
chips; it never parses prose.

**Квартал отправляется целиком.** Five goals replace five goals. Sending one
goal at a time would make the ceiling a question about the row being written,
and the row being written is never the one over the bar.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.models.goal import QUARTER_GOAL_MAX_ORD, QUARTER_GOAL_MIN_ORD


class GoalLevelResponse(BaseModel):
    """One `## Уровень N` block."""

    model_config = ConfigDict(from_attributes=True)

    level: int
    title: str
    body_md: str
    open_questions: list[str] = Field(
        description="Строки `⚠ подтверди` — то, что автор вывел сам и мог ошибиться"
    )


class MilestoneResponse(BaseModel):
    """One milestone, with the graph edge it waits on already resolved."""

    model_config = ConfigDict(from_attributes=True)

    code: str
    title: str
    done_criterion: str | None
    when_text: str | None
    ord: int
    status: str
    done_on: date | None
    depends_on: list[str] = Field(
        description="Коды милстонов, которыми этот открывается: у M10 — M8 и M9"
    )


class QuarterGoalResponse(BaseModel):
    """One of the five goals of a quarter."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    quarter: str
    ord: int
    text_md: str
    milestone_code: str | None
    status: str


class GoalsResponse(BaseModel):
    """The whole board: what the goal screen draws in one request."""

    levels: list[GoalLevelResponse]
    milestones: list[MilestoneResponse]
    quarter: str = Field(description="Текущий квартал в формате `2026-Q3`")
    goals: list[QuarterGoalResponse]


class MilestonePatch(BaseModel):
    """Moving one milestone to another status."""

    model_config = ConfigDict(extra="forbid")

    status: str = Field(
        description=(
            "Новый статус милстона. `done` проставляет дату закрытия сегодняшним "
            "днём по границе суток; любой другой статус её снимает"
        )
    )


class QuarterGoalIn(BaseModel):
    """One goal of a quarter, as it is sent."""

    model_config = ConfigDict(extra="forbid")

    ord: int = Field(
        ge=QUARTER_GOAL_MIN_ORD,
        le=QUARTER_GOAL_MAX_ORD,
        description="Место в списке, 1..5",
    )
    text_md: str
    milestone_code: str | None = None
    status: str = "open"


class QuarterGoalsIn(BaseModel):
    """
    The goals of a quarter, as one set.

    No `max_length` here on purpose: «больше пяти — цель размазана» is a rule the
    database owns (`ck_quarter_goal_ord`, `uq_quarter_goal_quarter_ord`), and a
    second copy of it in the schema would be the version that drifts.
    """

    model_config = ConfigDict(extra="forbid")

    goals: list[QuarterGoalIn]


__all__ = [
    "GoalLevelResponse",
    "GoalsResponse",
    "MilestonePatch",
    "MilestoneResponse",
    "QuarterGoalIn",
    "QuarterGoalResponse",
    "QuarterGoalsIn",
]
