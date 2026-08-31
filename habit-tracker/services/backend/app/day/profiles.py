# [review:need-review] PHASE-03/179
# summary: which ceiling a date is judged by and when to offer a different one — `resolve_profile` picks the confirmed activation covering the date (the later one wins an overlap, an unconfirmed one decides nothing, an expired one is simply gone) and `propose_profile` turns a near deadline plus a week of long days into a proposal with a reason, writing nothing anywhere
"""
Which ceiling of work a date is judged by, and when to offer a different one.

Both functions here are pure. The resolution is a total order over rows, and the
proposal is a judgement about signals; neither needs a session, and both are the
kind of thing that has to be checkable with two literals.

**Активация без подтверждения не действует.** That is the decision of
2026-08-30 expressed as a filter rather than as discipline: `resolve_profile`
never looks at a row whose `confirmed_at` is empty, so no ordering of calls
anywhere can let a proposal move a ceiling.

**Позже — сильнее.** Two confirmed activations covering the same date is a
legitimate state — a recovery week declared inside a deadline week — and the one
that starts later wins, with the id breaking a tie. Older-wins would mean a
correction made today could not take effect until the previous one expired.

**Срок кончается сам.** Nothing switches an activation off: a date outside
`[valid_from, valid_to]` simply has no activation, and the default profile
answers. That is the whole protection against a raised ceiling nobody remembers.

`propose_profile` is deliberately conservative. It proposes only when both halves
are true — a deadline is close *and* the last seven days already ran long — and
never proposes a reason that has already been refused. A proposal that appears on
every busy Tuesday is a proposal that gets clicked through.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

__all__ = [
    "MIN_LONG_DAYS",
    "Activation",
    "DeadlineSignal",
    "Profile",
    "Proposal",
    "baseline_profile",
    "propose_profile",
    "resolve_profile",
]

# How many days of the last seven have to have run past the baseline before a
# raise is worth offering. Two, not one: a single long day is a long day, and
# proposing a new ceiling for it would teach the person to click «принять».
MIN_LONG_DAYS = 2

# How close a deadline has to be to count as one. Three days — the horizon a
# person can actually plan the ceiling of, and past which the answer is «двигай
# срок», not «сиди дольше».
DEADLINE_HORIZON_DAYS = 3


@dataclass(frozen=True)
class Profile:
    """One named set of ceilings, as the resolver needs it: no ORM, no session."""

    id: int
    code: str
    title: str
    work_cap_min: int
    work_hard_cap_min: int
    is_default: bool = False


@dataclass(frozen=True)
class Activation:
    """One stretch of dates a profile ran over, and whether a person said so."""

    id: int
    profile_id: int
    valid_from: date
    valid_to: date
    confirmed: bool
    reason: str = ""

    def covers(self, on: date) -> bool:
        """Whether this activation has an opinion about `on`."""
        return self.valid_from <= on <= self.valid_to


@dataclass(frozen=True)
class DeadlineSignal:
    """
    A task of the work ClickUp whose due date is near.

    Plain values, and a signal rather than a decision: it is a reason to show a
    proposal and nothing more. The source of these is `#103`; until it lands,
    the list is simply empty and no proposal is ever made — which is the correct
    behaviour, not a degraded one.
    """

    task_id: str
    title: str
    due_on: date


@dataclass(frozen=True)
class Proposal:
    """
    An offer to raise the ceiling, with the reason it is being made.

    `reason` is a sentence a person reads, not a code: the whole point of the
    decision «система предлагает, человек подтверждает» is that the person is
    deciding, and a proposal that cannot say why is one nobody can weigh.
    """

    profile_code: str
    valid_from: date
    valid_to: date
    reason: str
    source_signal_id: str


def resolve_profile(
    profiles: list[Profile], activations: list[Activation], on: date
) -> Profile | None:
    """
    The profile in force on `on`: a confirmed activation's, or the default.

    `None` when the directory has no default — a database from before `#179`,
    or one nobody has seeded. The caller then judges the day by the ceiling of
    its own rule row, exactly as it did before this ticket: a feature that has
    not been set up must not change how a day was judged.
    """
    by_id = {profile.id: profile for profile in profiles}
    covering = [
        activation
        for activation in activations
        if activation.confirmed
        and activation.covers(on)
        and activation.profile_id in by_id
    ]
    if covering:
        winner = max(covering, key=lambda row: (row.valid_from, row.id))
        return by_id[winner.profile_id]

    return baseline_profile(profiles)


def baseline_profile(profiles: list[Profile]) -> Profile | None:
    """
    The ordinary ceiling, whatever is in force today, or `None` when unset.

    Debt is measured against this and never against the profile of the day —
    that is the sentence the whole ticket turns on. With no default there is no
    baseline, and therefore no debt: a system nobody set up owes nothing.
    """
    for profile in profiles:
        if profile.is_default:
            return profile
    return None


def propose_profile(
    *,
    signals: list[DeadlineSignal],
    long_days: int,
    today: date,
    declined_signal_ids: frozenset[str],
    active: bool,
) -> Proposal | None:
    """
    Whether to offer a raised ceiling right now, and with what reason.

    `None` is the normal answer. Four things all have to be true:

    * a deadline falls inside the next three days;
    * at least `MIN_LONG_DAYS` of the last seven already ran past the baseline —
      a raise for a week that is not actually long is a raise for nothing;
    * that signal has not already been refused — «предложение, от которого
      отказались, не показывается снова по той же причине»;
    * no activation is in force, because offering a second ceiling on top of one
      a person already accepted is how a twelve-hour week becomes a fourteen-hour
      one.

    Nothing is written anywhere. The caller shows this; only a confirmation
    moves a ceiling.
    """
    if active or long_days < MIN_LONG_DAYS:
        return None

    horizon = date.fromordinal(today.toordinal() + DEADLINE_HORIZON_DAYS)
    candidates = sorted(
        (
            signal
            for signal in signals
            if today <= signal.due_on <= horizon
            and signal.task_id not in declined_signal_ids
        ),
        key=lambda signal: (signal.due_on, signal.task_id),
    )
    if not candidates:
        return None

    nearest = candidates[0]
    return Proposal(
        profile_code="deadline",
        valid_from=today,
        valid_to=nearest.due_on,
        reason=(
            f"до {nearest.due_on.isoformat()} дедлайн «{nearest.title}», "
            f"и {long_days} из последних семи дней уже вышли за базовый потолок"
        ),
        source_signal_id=nearest.task_id,
    )
