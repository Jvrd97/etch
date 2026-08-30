# [review:need-review] PHASE-03/127
# summary: wire types of a challenge — a window the schema refuses to accept backwards or longer than 92 days, a threshold that must be present for `metric_*` and absent for the other two, and a read model that carries the count («день N из M, промахов K») rather than making the card derive it
"""
Проволочные типы обязательства.

**Окно проверяется здесь и в базе одновременно.** Схема отвечает человеку
внятным сообщением, `ck_challenge_window` отвечает всем остальным писателям.
Дублирование намеренное: сообщение об ошибке — не ограничение целостности, и
наоборот.

**Порог обязателен ровно там, где он что-то значит.** `metric_at_least` без
`target` не с чем сравнить, а `abstain` с `target` — это писатель, который
думает, что настроил что-то, чего нет. Оба случая — 422, а не тихий дефолт.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.challenge.rules import MAX_CHALLENGE_DAYS, METRIC_RULE_KINDS

RuleKind = Literal["metric_at_least", "metric_at_most", "checked", "abstain"]
DayVerdict = Literal["done", "miss", "pending"]
DaySource = Literal["computed", "manual"]
FailureMode = Literal["any_miss", "budget"]
ChallengeStatus = Literal["active", "won", "failed", "abandoned"]

WINDOW_BACKWARDS = (
    "окно челленджа не может кончиться раньше, чем началось: ends_on должен "
    "быть не раньше starts_on"
)
WINDOW_TOO_LONG = (
    f"окно челленджа длиннее {MAX_CHALLENGE_DAYS} дней: обязательство такой "
    "длины меряется не промахами по дням"
)
TARGET_REQUIRED = "правилу {kind} нужен порог target"
TARGET_NOT_ALLOWED = "правилу {kind} порог target не нужен и не применяется"
BUDGET_WITHOUT_MODE = (
    "allowed_misses > 0 имеет смысл только при failure_mode='budget': "
    "в режиме any_miss заваливает первый же промах"
)


def _validate_window(starts_on: date, ends_on: date) -> None:
    """Окно, которое можно прожить: не назад и не длиннее потолка."""
    if ends_on < starts_on:
        raise ValueError(WINDOW_BACKWARDS)
    if (ends_on - starts_on).days + 1 > MAX_CHALLENGE_DAYS:
        raise ValueError(WINDOW_TOO_LONG)


def _validate_target(kind: str, target: Decimal | None) -> None:
    """Порог там, где он что-то значит, и только там."""
    if kind in METRIC_RULE_KINDS and target is None:
        raise ValueError(TARGET_REQUIRED.format(kind=kind))
    if kind not in METRIC_RULE_KINDS and target is not None:
        raise ValueError(TARGET_NOT_ALLOWED.format(kind=kind))


class ChallengeIn(BaseModel):
    """Челлендж, каким его заводят."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=200)
    category_id: int
    field_id: int
    rule_kind: RuleKind
    target: Decimal | None = Field(
        None, description="Порог для metric_at_least / metric_at_most"
    )
    starts_on: date
    ends_on: date
    failure_mode: FailureMode = Field(
        "any_miss", description="any_miss — валит первый промах; budget — N+1-й"
    )
    allowed_misses: int = Field(0, ge=0, le=MAX_CHALLENGE_DAYS)

    @model_validator(mode="after")
    def check(self) -> ChallengeIn:
        _validate_window(self.starts_on, self.ends_on)
        _validate_target(self.rule_kind, self.target)
        if self.failure_mode == "any_miss" and self.allowed_misses:
            raise ValueError(BUDGET_WITHOUT_MODE)
        return self


class ChallengePatch(BaseModel):
    """
    Что у челленджа можно поменять на ходу.

    Правила (`category_id`, `field_id`, `rule_kind`) и начала окна здесь нет:
    поменять, про что было обещание, — значит завести другое обещание, а не
    отредактировать это. Правка `target` разрешена и прошлые вердикты не
    трогает — они посчитаны правилом своего времени.
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(None, min_length=1, max_length=200)
    target: Decimal | None = None
    ends_on: date | None = None
    failure_mode: FailureMode | None = None
    allowed_misses: int | None = Field(None, ge=0, le=MAX_CHALLENGE_DAYS)


class ChallengeDayResponse(BaseModel):
    """Один день обязательства."""

    model_config = ConfigDict(from_attributes=True)

    day: date
    verdict: DayVerdict
    source: DaySource
    note: str | None = None


class ChallengeResponse(BaseModel):
    """
    Челлендж, каким его читает карточка.

    Счёт приезжает готовым — `day_number`, `total_days`, `misses_used`. Карточка
    печатает «день 3 из 7, промахов 0», и считать это на клиенте значило бы
    завести второе место, где живёт арифметика обязательства.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    category_id: int
    field_id: int
    rule_kind: RuleKind
    target: Decimal | None
    starts_on: date
    ends_on: date
    failure_mode: FailureMode
    allowed_misses: int
    status: ChallengeStatus
    failed_on: date | None

    total_days: int = Field(..., description="Длина окна в днях")
    day_number: int = Field(
        ...,
        description=(
            "Какой день окна идёт сейчас: 0 до старта, total_days после конца"
        ),
    )
    done_count: int
    misses_used: int
    today_verdict: DayVerdict | None = Field(
        None, description="Состояние сегодняшнего дня; null, если он вне окна"
    )

    created_at: datetime


class ChallengeDetailResponse(ChallengeResponse):
    """Челлендж со всеми материализованными днями."""

    days: list[ChallengeDayResponse]
