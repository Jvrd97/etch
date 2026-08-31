# [review:need-review] PHASE-03/179
# summary: the ceiling of work as data that breathes — `day_rule_profile` (named sets of caps, exactly one default), `day_rule_activation` (which profile ran on which dates, why, and whether a person confirmed it — an unconfirmed row decides nothing) and `overtime_debt` (a day over the baseline owes minutes, and a week with an unpaid debt is not won)
"""
The ceiling of work, as a thing that bends without breaking.

600 minutes as a constant in a rule row does not describe how the work actually
goes: in the week a release ships, ten hours is normal; in a quiet one it is
already too much. These three tables make the ceiling a function of the
situation without losing the reason the rule exists at all.

**Опасность названа прямо: потолок, который сам растёт под дедлайн, отменяет
правило.** «Переработка = проигранный день» exists so that urgency cannot excuse
a twelve-hour day. So a raised ceiling is not free — it creates a debt, and until
the debt is repaid the week is not won. Flexibility is bought back, not handed
out.

**Система предлагает, человек подтверждает** (решение 2026-08-30). There is no
automatic raise anywhere in this module. A deadline arriving from the work
ClickUp is a reason to *show* a proposal; the ceiling is moved by
`confirmed_at`, never by the signal.

**Активация кончается сама.** Every activation carries `valid_to`, after which
the ceiling returns to the default with nobody switching anything off. That is
the main way such concessions stop being concessions — somebody forgets they are
on — and the schema removes the possibility rather than the temptation.

`overtime_debt` counts minutes over the **baseline** ceiling, not over the raised
one. A day at eleven hours under a twelve-hour profile is a won day that owes an
hour; counting the overage against the raised ceiling would make the debt always
zero and the whole mechanism decorative.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base

# The three named sets. Codes rather than titles: a title is what a screen
# prints and a person may rewrite, a code is what an activation points at.
PROFILE_BASELINE = "baseline"
PROFILE_DEADLINE = "deadline"
PROFILE_RECOVERY = "recovery"
PROFILE_CODES: tuple[str, ...] = (
    PROFILE_BASELINE,
    PROFILE_DEADLINE,
    PROFILE_RECOVERY,
)

# Who may confirm an activation. One value, and a column rather than a comment:
# «система предлагает, человек подтверждает» is the decision of 2026-08-30, and
# a row that could be confirmed by anything else would be that decision undone.
CONFIRMED_BY_HUMAN = "human"
CONFIRMERS: tuple[str, ...] = (CONFIRMED_BY_HUMAN,)


def _in_list(column: str, values: tuple[str, ...]) -> str:
    """`code IN ('a', 'b')` — spelled once for the model and the migration."""
    joined = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({joined})"


class DayRuleProfile(Base):
    """
    One named set of ceilings the day can be judged by.

    Not a new canon and not a copy of `day_rule_set`: the canon of the day —
    the boundary, the edges, the free evening — stays one, and a profile
    overrides the two numbers that legitimately differ between a release week
    and a quiet one. Everything else about the day is the same rule.

    Exactly one row is the default, enforced by a partial unique index rather
    than by whoever writes: a system with two defaults has no answer to «по
    какому потолку судится обычный день», and a system with none has no way to
    end an activation.
    """

    __tablename__ = "day_rule_profile"
    __table_args__ = (
        CheckConstraint(
            _in_list("code", PROFILE_CODES), name="ck_day_rule_profile_code"
        ),
        CheckConstraint(
            "work_cap_min > 0 AND work_hard_cap_min >= work_cap_min",
            name="ck_day_rule_profile_caps",
        ),
        # Ровно один профиль по умолчанию. Частичный: строк без флага много, и
        # уникальность по колонке целиком запретила бы вторую из них.
        Index(
            "uq_day_rule_profile_default",
            "is_default",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(100))

    work_cap_min: Mapped[int] = mapped_column(Integer)
    work_hard_cap_min: Mapped[int] = mapped_column(Integer)
    # Which anchors of the canon this profile requires. A list rather than a
    # flag, because a recovery week legitimately asks for more of them than a
    # release week does; empty means «те же, что у правила дня».
    required_anchors: Mapped[list[Any]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    is_default: Mapped[bool] = mapped_column(Boolean, server_default="false")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<DayRuleProfile(code='{self.code}', cap={self.work_cap_min})>"


class DayRuleActivation(Base):
    """
    Which profile was in force over which dates, why, and on whose word.

    `confirmed_at` is the whole mechanism. A row without it decides nothing —
    it is a proposal that was shown and either not answered or refused, and it
    is kept rather than deleted so the same reason is not proposed again the
    next morning.

    `valid_to` is NOT NULL on purpose. An activation without an end is a raised
    ceiling nobody remembers to lower, which is exactly the failure this table
    exists to prevent.

    `RESTRICT` on the profile: deleting a profile out from under the dates it
    judged would leave those days measured against nothing.
    """

    __tablename__ = "day_rule_activation"
    __table_args__ = (
        CheckConstraint("valid_to >= valid_from", name="ck_day_rule_activation_range"),
        CheckConstraint(
            _in_list("confirmed_by", CONFIRMERS) + " OR confirmed_by IS NULL",
            name="ck_day_rule_activation_confirmed_by",
        ),
        CheckConstraint(
            "confirmed_at IS NULL OR confirmed_by IS NOT NULL",
            name="ck_day_rule_activation_confirmed_pair",
        ),
        Index("ix_day_rule_activation_range", "valid_from", "valid_to"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("day_rule_profile.id", ondelete="RESTRICT"), index=True
    )

    valid_from: Mapped[date_type] = mapped_column(Date)
    valid_to: Mapped[date_type] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(Text)

    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    confirmed_by: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # The moment a person said no. A refused proposal stays as a row so the same
    # reason is not offered again — «предложение, от которого отказались, не
    # показывается снова по той же причине».
    declined_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # What made the system propose this: the task of the work ClickUp whose
    # deadline is near. Free text rather than a foreign key — the inbox of `#103`
    # is not in this database yet, and a key to a table that does not exist is
    # not a key.
    source_signal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    profile: Mapped[DayRuleProfile] = relationship()

    def __repr__(self) -> str:
        return (
            f"<DayRuleActivation(profile_id={self.profile_id}, "
            f"{self.valid_from}..{self.valid_to}, "
            f"confirmed={self.confirmed_at is not None})>"
        )


class OvertimeDebt(Base):
    """
    Minutes one day ran over the **baseline** ceiling, and whether they came back.

    One row per day, enforced by the primary key on the date: a day owes what it
    owes, and a second row for the same date would be the day counted twice.

    Over the baseline rather than over the raised ceiling — that is the sentence
    the whole ticket turns on. A day at eleven hours under a twelve-hour profile
    is won *and* owes an hour; measuring the overage against the profile in force
    would make every debt zero and the mechanism decorative.
    """

    __tablename__ = "overtime_debt"
    __table_args__ = (
        CheckConstraint("minutes_over > 0", name="ck_overtime_debt_positive"),
        CheckConstraint(
            "(repaid_on IS NULL) = (repaid_by_day IS NULL)",
            name="ck_overtime_debt_repaid_pair",
        ),
        Index(
            "ix_overtime_debt_open",
            "incurred_on",
            postgresql_where=text("repaid_on IS NULL"),
        ),
    )

    incurred_on: Mapped[date_type] = mapped_column(Date, primary_key=True)
    minutes_over: Mapped[int] = mapped_column(Integer)

    repaid_on: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    # The day that paid it back. `SET NULL` rather than `RESTRICT`: deleting a
    # day is rare and the debt outliving its repayment reads as «долг вернулся,
    # день не сохранился», which is true and better than a refused delete.
    repaid_by_day: Mapped[date_type | None] = mapped_column(
        Date,
        ForeignKey("day.date", ondelete="SET NULL", name="fk_overtime_debt_repaid_by"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"<OvertimeDebt(on={self.incurred_on}, minutes={self.minutes_over}, "
            f"repaid={self.repaid_on})>"
        )
