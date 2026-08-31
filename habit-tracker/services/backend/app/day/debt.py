# [review:need-review] PHASE-03/179
# summary: the price of a raised ceiling — `accrue` counts the minutes a day ran over the **baseline** (never over the profile in force, and never for a day nobody measured) and `repay` picks the oldest open debt a short day can actually pay back, plus the reading of a week that is not won while anything is still owed
"""
What a raised ceiling costs.

«Переработка = проигранный день» exists so that urgency cannot excuse a
twelve-hour day. A profile that simply raised the ceiling would delete that rule
and keep its name. So the raise is bought: every minute over the *baseline*
becomes a debt, and a week with an open debt is not won however each of its days
was judged.

Two rules carry the whole module, and both are one line of code and one
paragraph of reason.

**Долг считается от базового потолка.** A day at eleven hours under a
twelve-hour profile is a won day that owes an hour. Measuring the overage
against the profile in force would make every debt zero, and the mechanism would
be decoration on top of an abolished rule.

**Гасит день, который реально короче.** A debt is repaid by a day whose measured
work leaves room for it under the baseline — not by any short day and not
partially. Partial repayment would let an hour of overtime be paid off in
five-minute change over a fortnight, which is not the recovery the rule is
asking for.

A day nobody measured (`work_minutes IS NULL`) neither accrues nor repays. That
is the same reading `evaluate_day` gives it: «не измерено» is not zero, and a day
with no intervals must not quietly repay a debt.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

__all__ = ["Debt", "accrue", "repay", "week_is_won"]


@dataclass(frozen=True)
class Debt:
    """One day's overage, and the day that paid it back if one has."""

    incurred_on: date
    minutes_over: int
    repaid_on: date | None = None

    @property
    def is_open(self) -> bool:
        return self.repaid_on is None


def accrue(work_minutes: int | None, baseline_cap_min: int) -> int:
    """
    How many minutes a day owes. Zero when it owes nothing.

    Against the baseline, always. `work_minutes IS NULL` owes nothing — the day
    was not measured, and inventing a zero for it would let an unmeasured day
    look like a short one.
    """
    if work_minutes is None:
        return 0
    over = work_minutes - baseline_cap_min
    return over if over > 0 else 0


def repay(
    debts: list[Debt], work_minutes: int | None, baseline_cap_min: int
) -> Debt | None:
    """
    The debt this day pays back, or `None` when it pays back nothing.

    The oldest open debt that fits, not an arbitrary one: paying the newest
    first would let an old debt sit forever behind a stream of new ones, and
    «долг, висящий дольше недели» is the thing the week screen is supposed to
    make impossible to miss.

    «Fits» means the day's measured work leaves the whole debt under the
    baseline: a sixty-minute debt is repaid by a day of seven hours when the
    baseline is eight, and not by a day of seven hours and fifty minutes.
    """
    if work_minutes is None:
        return None
    room = baseline_cap_min - work_minutes
    if room <= 0:
        return None
    open_debts = sorted(
        (debt for debt in debts if debt.is_open), key=lambda debt: debt.incurred_on
    )
    for debt in open_debts:
        if debt.minutes_over <= room:
            return debt
    return None


def week_is_won(won_days: int, total_days: int, open_debt_minutes: int) -> bool:
    """
    Whether a week counts as won.

    Three conditions, and the third is what this ticket adds: every day of the
    week was won, the week actually had days, and nothing is still owed. A week
    of seven won days carrying an unpaid hour of overtime is not a won week —
    that is precisely the trade the raised ceiling was sold on.
    """
    return total_days > 0 and won_days == total_days and open_debt_minutes == 0
