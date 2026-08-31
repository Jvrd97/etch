# [review:need-review] PHASE-03/179
# summary: wire types of the breathing ceiling — a profile named by code, the profile in force on a date with the date its raise runs out, a proposal that always carries its reason, the confirmation a person signs (`valid_to` and `reason` both required) and the debt ledger with what is still owed
"""
Wire types of the work-ceiling profiles and of the overtime debt.

**Профиль называется кодом.** Every write names `profile_code`; the id is an
answer, never a question — the same convention the roles use, and for the same
reason: `"deadline"` reads and `3` does not.

**У активации нет бессрочной формы.** `valid_to` and `reason` are both required
on the wire, not optional with a default. An activation without an end is a
raised ceiling nobody remembers to lower; one without a reason is a raise nobody
can weigh a month later.

**Предложение всегда несёт причину.** `GET /day/rules/proposal` either answers
with a sentence naming the task and its due date, or answers with nothing. There
is deliberately no shape in which it can propose something silently.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.day_profile import PROFILE_CODES


class DayRuleProfileResponse(BaseModel):
    """One named set of ceilings."""

    id: int
    code: str
    title: str
    work_cap_min: int
    work_hard_cap_min: int
    required_anchors: list[str] = Field(default_factory=list)
    is_default: bool


class DayRuleProfileIn(BaseModel):
    """A profile as it is written or corrected."""

    model_config = ConfigDict(extra="forbid")

    code: str
    title: str = Field(min_length=1, max_length=100)
    work_cap_min: int = Field(gt=0)
    work_hard_cap_min: int = Field(gt=0)
    required_anchors: list[str] = Field(default_factory=list)
    is_default: bool = False

    @field_validator("code")
    @classmethod
    def _check_code(cls, value: str) -> str:
        if value not in PROFILE_CODES:
            raise ValueError(f"code must be one of: {', '.join(PROFILE_CODES)}")
        return value


class ProfileInForceResponse(BaseModel):
    """
    Which ceiling a day is judged by, and until when.

    `valid_to` is null on an ordinary day: the default profile is not «до
    какого-то числа», it is simply how the day is judged.
    """

    code: str
    title: str
    work_cap_min: int
    valid_to: date | None = Field(
        default=None, description="Дата, после которой потолок сам вернётся к базовому"
    )
    reason: str = ""


class ProfileProposalResponse(BaseModel):
    """
    An offer to raise the ceiling, or nothing at all.

    `proposal` is null far more often than not, and that is the normal answer —
    a proposal on every busy Tuesday is a proposal that gets clicked through.
    """

    profile_code: str
    title: str
    work_cap_min: int
    valid_from: date
    valid_to: date
    reason: str = Field(
        description="Почему предлагается: задача и её срок, а не «система считает»"
    )
    source_signal_id: str


class ActivationIn(BaseModel):
    """
    A person confirming a raised ceiling. Both the end and the reason are required.

    Не поле с умолчанием: активация без срока — это потолок, который некому
    выключить, и именно так послабления перестают быть послаблениями.
    """

    model_config = ConfigDict(extra="forbid")

    profile_code: str
    valid_from: date
    valid_to: date
    reason: str = Field(min_length=1)
    source_signal_id: str | None = Field(default=None, max_length=64)

    @field_validator("profile_code")
    @classmethod
    def _check_code(cls, value: str) -> str:
        if value not in PROFILE_CODES:
            raise ValueError(f"profile_code must be one of: {', '.join(PROFILE_CODES)}")
        return value


class ActivationResponse(BaseModel):
    """One activation, with whether it actually decides anything."""

    id: int
    profile_code: str
    valid_from: date
    valid_to: date
    reason: str
    confirmed_at: datetime | None
    declined_at: datetime | None
    source_signal_id: str | None
    is_in_force: bool = Field(
        description="Подтверждена и не истекла — только такая двигает потолок"
    )


class DebtResponse(BaseModel):
    """One day's overtime, and whether it has come back."""

    incurred_on: date
    minutes_over: int
    repaid_on: date | None
    repaid_by_day: date | None
    is_open: bool
    days_open: int = Field(
        description="Сколько дней долг висит; больше семи — проваленное правило, а не справка"
    )


class DebtLedgerResponse(BaseModel):
    """The whole ledger, plus the one number a week is judged with."""

    open_minutes: int
    debts: list[DebtResponse]


__all__ = [
    "ActivationIn",
    "ActivationResponse",
    "DayRuleProfileIn",
    "DayRuleProfileResponse",
    "DebtLedgerResponse",
    "DebtResponse",
    "ProfileInForceResponse",
    "ProfileProposalResponse",
]
