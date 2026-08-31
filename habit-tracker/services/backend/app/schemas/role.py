# [review:need-review] PHASE-03/134, PHASE-03/135, PHASE-03/140
# summary: wire types of the roles — the directory with its target share flagged as a hypothesis, the rules (regex validated before it can be stored), minutes and acts written by role code, and the day view that carries both the distribution of minutes and the acts of the day; #140 lets an act from the plan name the line of the plan it came from; #135 makes an automatic record explain itself — the rule that produced it and the application it was measured from — and adds the answer of one markup run
"""
Wire types of the roles.

**Роль называется кодом, не числом.** Every write names `role_code`; the id is
an answer, never a question. It keeps a request readable (`"role_code":
"architect"`) and keeps the four seeded roles addressable without a lookup.

**Словарь `act_kind` живёт здесь.** The column is a plain string by ADR-0020 B1,
so the list of kinds the API accepts grows by editing this module — a pull
request, not a migration.

**Минуты не проверяются здесь.** There is deliberately no `gt=0` on `minutes`:
«ноль минут отвергается базой, а не сервисом» is an acceptance condition, and a
copy of the bar in the schema would be the copy that drifts. The API turns the
database's refusal into a 422.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from app.models.role import (
    CONFIDENCE_AUTO,
    MATCHER_KINDS,
    MATCHER_WINDOW_TITLE_REGEX,
    ROLE_ACT_SOURCES,
    ROLE_CONFIDENCES,
    ROLE_TIME_SOURCES,
    RULE_PRIORITY_DEFAULT,
    SOURCE_MANUAL,
)

# What an act can be. Straight out of the job description: the decisions and
# artefacts that make a role visible on a day, not the hours it took to make
# them.
ACT_KINDS: tuple[str, ...] = (
    "adr_written",
    "data_model_decision",
    "security_review",
    "roadmap_update",
    "budget_decision",
    "hiring_step",
    "report_to_management",
    "partner_talk",
    "code_review",
    "ci_change",
    "wrote_from_scratch",
)


def _one_of(value: str, allowed: tuple[str, ...], field_name: str) -> str:
    """Membership check shared by every vocabulary field, error text included."""
    if value not in allowed:
        raise ValueError(f"{field_name} must be one of: {', '.join(allowed)}")
    return value


class RoleResponse(BaseModel):
    """One role of the directory."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    title: str
    description: str | None
    target_share_pct: int | None = Field(
        default=None,
        description=(
            "Целевая доля минут за квартал. Гипотеза, а не норма: день по ней "
            "не судится"
        ),
    )
    is_work: bool
    ord: int
    is_active: bool


class RoleCreate(BaseModel):
    """A new role. The code is what everything else will point at."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=20)
    title: str = Field(min_length=1, max_length=100)
    description: str | None = None
    target_share_pct: int | None = Field(default=None, ge=0, le=100)
    is_work: bool = True
    ord: int = 0
    is_active: bool = True


class RolePatch(BaseModel):
    """
    A change to a role. The code is absent on purpose.

    Renaming a code would silently orphan every rule, minute and act that names
    it in a request; the title is the field a person actually wants to rewrite.
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    target_share_pct: int | None = Field(default=None, ge=0, le=100)
    is_work: bool | None = None
    ord: int | None = None
    is_active: bool | None = None


class RoleRuleResponse(BaseModel):
    """One line of the markup, as it is stored."""

    id: int
    role_id: int
    role_code: str
    source: str
    matcher_kind: str
    pattern: str
    priority: int = Field(description="Меньше — сильнее; равенство решается по id")
    is_active: bool


class RoleRuleCreate(BaseModel):
    """
    A new rule.

    A `window_title_regex` is compiled here rather than at match time: a pattern
    that cannot compile is a rule that would silently never fire, and the moment
    to say so is while the person who wrote it is still looking.
    """

    model_config = ConfigDict(extra="forbid")

    role_code: str
    source: str
    matcher_kind: str
    pattern: str = Field(min_length=1, max_length=500)
    priority: int = RULE_PRIORITY_DEFAULT
    is_active: bool = True

    @field_validator("source")
    @classmethod
    def _check_source(cls, value: str) -> str:
        return _one_of(value, ROLE_TIME_SOURCES, "source")

    @field_validator("matcher_kind")
    @classmethod
    def _check_matcher_kind(cls, value: str) -> str:
        return _one_of(value, MATCHER_KINDS, "matcher_kind")

    @field_validator("pattern")
    @classmethod
    def _check_pattern(cls, value: str, info: ValidationInfo) -> str:
        # `info.data` carries the already-validated fields; a pattern is only a
        # regex when the kind says so, and a glob like `*/habit_tracker_ai/*` is
        # not required to be one.
        if info.data.get("matcher_kind") != MATCHER_WINDOW_TITLE_REGEX:
            return value
        try:
            re.compile(value)
        except re.error as error:
            raise ValueError(
                f"pattern is not a valid regular expression: {error}"
            ) from error
        return value


class RoleRulePatch(BaseModel):
    """A change to a rule: its weight, its pattern or whether it applies at all."""

    model_config = ConfigDict(extra="forbid")

    role_code: str | None = None
    pattern: str | None = Field(default=None, min_length=1, max_length=500)
    priority: int | None = None
    is_active: bool | None = None


class RoleTimeBlockResponse(BaseModel):
    """Minutes charged to a role on a day."""

    id: int
    work_day: date
    role_id: int
    role_code: str
    source: str
    started_at: datetime | None
    ended_at: datetime | None
    minutes: int
    confidence: str
    external_ref: str | None
    rule_id: int | None
    note: str | None
    is_manual: bool = Field(
        description="Ручная запись — то, что человек ввёл сам; экран помечает её"
    )
    is_automatic: bool = Field(
        default=False,
        description=(
            "Запись, посчитанная разметкой активности. Экран помечает её и даёт "
            "кнопку «подтвердить»"
        ),
    )
    rule_summary: str | None = Field(
        default=None,
        description=(
            "Правило, которое создало запись, одной строкой: «bundle_id = "
            "com.microsoft.VSCode». Без него неверная разметка неотличима от верной"
        ),
    )
    app_name: str | None = Field(
        default=None, description="Приложение, из которого запись посчитана"
    )


class RoleTimeBlockIn(BaseModel):
    """
    Minutes, as they are written.

    `work_day` may be omitted, and then the server dates the record by its own
    day boundary (`app.core.daytime`) instead of by the browser's calendar. The
    manual form fills it in from the date field; an importer of `#135` will
    compute it from the interval it is charging.
    """

    model_config = ConfigDict(extra="forbid")

    role_code: str
    minutes: int = Field(
        description="Минуты. Ноль и отрицательные отвергает база, а не схема"
    )
    work_day: date | None = None
    source: str = SOURCE_MANUAL
    started_at: datetime | None = None
    ended_at: datetime | None = None
    confidence: str = CONFIDENCE_AUTO
    external_ref: str | None = Field(default=None, max_length=200)
    rule_id: int | None = None
    note: str | None = None

    @field_validator("source")
    @classmethod
    def _check_source(cls, value: str) -> str:
        return _one_of(value, ROLE_TIME_SOURCES, "source")

    @field_validator("confidence")
    @classmethod
    def _check_confidence(cls, value: str) -> str:
        return _one_of(value, ROLE_CONFIDENCES, "confidence")


class RoleTimeBlockPatch(BaseModel):
    """
    A person's correction of one record of minutes.

    This is the other half of «ручное поверх автоматики»: whatever an importer
    computed, the row can be re-pointed, re-measured and marked `confirmed`,
    after which no importer touches it again.
    """

    model_config = ConfigDict(extra="forbid")

    role_code: str | None = None
    minutes: int | None = None
    work_day: date | None = None
    confidence: str | None = None
    note: str | None = None

    @field_validator("confidence")
    @classmethod
    def _check_confidence(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _one_of(value, ROLE_CONFIDENCES, "confidence")


class RoleActResponse(BaseModel):
    """One act: the role happened, and this is what it was."""

    id: int
    work_day: date
    role_id: int
    role_code: str
    act_kind: str
    title: str
    source: str
    external_ref: str | None
    confidence: str
    occurred_at: datetime | None
    note: str | None
    is_manual: bool
    plan_item_id: UUID | None = Field(
        default=None,
        description=(
            "Пункт плана, галочка на котором закрыла этот акт. Есть только у "
            "актов с source='plan'"
        ),
    )
    plan_item_text: str | None = Field(
        default=None,
        description="Текст того пункта, чтобы акт раскрывался на экране до строки плана",
    )


class RoleActIn(BaseModel):
    """An act, as it is written. Kind, title and day — nothing else is required."""

    model_config = ConfigDict(extra="forbid")

    role_code: str
    act_kind: str
    title: str = Field(min_length=1, max_length=200)
    work_day: date | None = None
    source: str = SOURCE_MANUAL
    external_ref: str | None = Field(default=None, max_length=200)
    confidence: str = CONFIDENCE_AUTO
    occurred_at: datetime | None = None
    note: str | None = None

    @field_validator("act_kind")
    @classmethod
    def _check_act_kind(cls, value: str) -> str:
        return _one_of(value, ACT_KINDS, "act_kind")

    @field_validator("source")
    @classmethod
    def _check_source(cls, value: str) -> str:
        return _one_of(value, ROLE_ACT_SOURCES, "source")

    @field_validator("confidence")
    @classmethod
    def _check_confidence(cls, value: str) -> str:
        return _one_of(value, ROLE_CONFIDENCES, "confidence")


class RoleActPatch(BaseModel):
    """A person's correction of one act."""

    model_config = ConfigDict(extra="forbid")

    role_code: str | None = None
    act_kind: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    work_day: date | None = None
    confidence: str | None = None
    note: str | None = None

    @field_validator("act_kind")
    @classmethod
    def _check_act_kind(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _one_of(value, ACT_KINDS, "act_kind")

    @field_validator("confidence")
    @classmethod
    def _check_confidence(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _one_of(value, ROLE_CONFIDENCES, "confidence")


class RoleDaySlice(BaseModel):
    """One role's share of one day: minutes, the share they make, and the acts."""

    role_id: int
    role_code: str
    title: str
    minutes: int
    share_pct: int = Field(
        description="Доля минут дня, целые проценты; 0 у роли без минут"
    )
    target_share_pct: int | None = Field(
        default=None, description="Гипотеза квартала, не норма дня"
    )
    act_count: int


class RoleClassifyIn(BaseModel):
    """
    Диапазон дат, который надо разметить заново.

    Диапазон, а не день: честный повод запустить разметку руками — «поправил
    правило, переразметь неделю», и семь запросов на это сделали бы экран правил
    неудобным ровно там, где он нужен.
    """

    model_config = ConfigDict(extra="forbid")

    date_from: date
    date_to: date


class RoleClassifyDay(BaseModel):
    """Что разметка сделала с одним днём."""

    work_day: date
    mode: str = Field(description="Режим дня: вне рабочего минуты не разносятся вовсе")
    intervals: int
    blocks_written: int
    kept_confirmed: int = Field(
        description="Записи, подтверждённые человеком: разметка их не тронула"
    )
    minutes: int
    unassigned_minutes: int
    skipped_off_mode: int
    skipped_short: int = Field(description="Куски короче минуты: минут не дают")


class RoleClassifyResponse(BaseModel):
    """Ответ прогона: по строке на день, старые первыми."""

    days: list[RoleClassifyDay]


class RoleDayResponse(BaseModel):
    """
    What `/roles` draws: where the day went and whether the roles happened.

    Both halves in one request, because neither answers the question alone —
    that is the whole of decision B2, carried through to the wire.
    """

    work_day: date
    total_minutes: int
    roles: list[RoleDaySlice]
    blocks: list[RoleTimeBlockResponse]
    acts: list[RoleActResponse]


__all__ = [
    "ACT_KINDS",
    "RoleActIn",
    "RoleClassifyDay",
    "RoleClassifyIn",
    "RoleClassifyResponse",
    "RoleActPatch",
    "RoleActResponse",
    "RoleCreate",
    "RoleDayResponse",
    "RoleDaySlice",
    "RolePatch",
    "RoleResponse",
    "RoleRuleCreate",
    "RoleRulePatch",
    "RoleRuleResponse",
    "RoleTimeBlockIn",
    "RoleTimeBlockPatch",
    "RoleTimeBlockResponse",
]
