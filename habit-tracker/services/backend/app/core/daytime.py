# [review:need-review] PHASE-03/107, PHASE-03/86, PHASE-03/90, PHASE-03/91, PHASE-03/113
# summary: the single day boundary — local_date()/day_bounds()/now_utc() over the boundary published from the day_rule_set row in force, settings only until one is published; a naive datetime is refused, not assumed to be UTC; since #90 nothing in app/ counts days any other way
# summary: PHASE-03/113 adds local_time() — the wall clock of a stored moment, so a card printing a plan window does not open a second zone of its own
"""
The one answer to "which day does this moment belong to".

Nine tickets of this phase attach data to a day, and before this module they
would have answered in two different ways: a versioned `day_start_hour` in one
place, a plain calendar date in `Europe/Berlin` in another. A water mark at
00:30 would then land in one day and a work interval at 00:30 in the previous
one, and a single day screen would show two different "todays".

So there is one rule and one module. A day runs from the boundary hour of local
wall clock to the same hour of the next calendar date; a moment at 00:30 belongs
to the previous day, everywhere, with no exception for "tracker" data. Anyone
who needs a local date calls `local_date()`; anyone who needs a range for a SQL
query calls `day_bounds()`. A second function of this kind appearing anywhere in
`app/` is a reason to reopen review, not to reconcile the difference.

**Where the boundary comes from.** The zone and the start hour are two columns
of the `day_rule_set` row in force (`#86`): the canon of a day is data, and the
boundary is part of that canon. `app.crud.day` reads the row and publishes it
here with `use_boundary()`; from then on every call in the process reads the
table's answer. Until something publishes — a process that has not touched the
day API yet, a database that has not been migrated — the fallback is
`settings.APP_TIMEZONE` / `settings.DAY_START_HOUR`, whose defaults are the
seeded row's values.

The boundary is a process-wide value rather than an argument on purpose. Making
it a parameter would turn a change of source into an edit of every one of the
nine call sites, and would let two of them disagree; that is exactly the failure
this module exists to prevent. It is also why the signature
`local_date(at: datetime) -> date` survived the move of the source.

One consequence worth naming: the boundary is the *current* rule's, not the
rule's in force on the date being asked about. A day is looked up by the local
date it already has, and re-answering an old moment under an old boundary would
move rows between days years after the fact. Should the boundary hour ever
actually change, the past keeps the dates it was recorded with.

Consumers: `#86` (a moment's day), `#90` (the verdict of a day and the streak of
categories), `#91` (work intervals), `#97` (a signal's `local_date`), `#121`
(quick marks), `#124` (undo), `#127` (challenges), `#134`/`#135` (role minutes),
`#146` (day signals). Since `#90` there is no second arithmetic of days left in
`app/`: `app.crud.streak` counted UTC ones and now asks here like everyone else.

Related: ADR-0014 (day in postgres), ADR-0016 (external inbox), ADR-0018
(challenges and quick marks).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.core.config import settings

__all__ = [
    "DayBoundary",
    "current_boundary",
    "day_bounds",
    "local_date",
    "local_time",
    "now_utc",
    "reset_boundary",
    "today_local",
    "use_boundary",
]


def now_utc() -> datetime:
    """
    The current moment, aware and in UTC.

    Here rather than at each call site so that nobody spells it `datetime.now()`
    without a zone: `local_date()` refuses a naive datetime by design, and the
    fix for that refusal is worth having in exactly one spelling.
    """
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class DayBoundary:
    """
    Where one day ends and the next begins: an IANA zone and the hour it turns.

    Two columns of `day_rule_set`, carried as a value so that this module never
    imports a model, a session or anything that would drag the database into a
    function three quarters of the codebase calls.
    """

    timezone: str
    day_start_hour: int


# The published boundary; None means "nothing has read the table yet", which is
# the only state in which settings are consulted.
_boundary: DayBoundary | None = None


def use_boundary(boundary: DayBoundary) -> None:
    """
    Publish the boundary of the rule in force; every later call reads it.

    Called by `app.crud.day` whenever it loads the rule rows — on startup and on
    every request that touches a day — so a rule inserted while the process runs
    takes effect without a restart.
    """
    global _boundary
    _boundary = boundary


def reset_boundary() -> None:
    """Forget the published boundary and fall back to settings. For tests."""
    global _boundary
    _boundary = None


def current_boundary() -> DayBoundary:
    """
    The boundary in force in this process.

    The settings fallback is not a second rule: its defaults are the values of
    the seeded rule row, so a process that has not read the table yet answers the
    same thing the table would have answered.
    """
    if _boundary is not None:
        return _boundary
    return DayBoundary(
        timezone=settings.APP_TIMEZONE, day_start_hour=settings.DAY_START_HOUR
    )


def _zone(boundary: DayBoundary) -> ZoneInfo:
    """
    The boundary's IANA zone.

    `ZoneInfo` caches its instances, so this is a dictionary lookup rather than a
    file read, and resolving it per call is what lets a newly published rule take
    effect without touching a caller.
    """
    return ZoneInfo(boundary.timezone)


def local_date(at: datetime) -> date:
    """
    The day the moment `at` belongs to.

    The day starts at the boundary hour of local wall clock: with the seeded
    hour of 4, 03:59 belongs to the previous date and 04:00 to the current one.
    `at` must be timezone-aware — a naive datetime is refused rather than
    silently read as UTC, because "silently read as UTC" is exactly the bug this
    module exists to prevent.
    """
    if at.tzinfo is None or at.tzinfo.utcoffset(at) is None:
        raise ValueError(
            "local_date() needs a timezone-aware datetime: a naive one has no "
            "single answer and would be silently read as UTC, shifting the day "
            f"by the local offset. Got {at!r}; use "
            "datetime.now(timezone.utc) or attach the origin's tzinfo."
        )
    boundary = current_boundary()
    # Wall-clock arithmetic on purpose: aware datetimes subtract inside their
    # own zone, so this reads the local clock `day_start_hour` hours earlier and
    # takes its date. Across a DST transition the intermediate value may carry
    # a stale offset, which does not matter — only `.date()` is used.
    shifted = at.astimezone(_zone(boundary)) - timedelta(hours=boundary.day_start_hour)
    return shifted.date()


def local_time(at: datetime) -> time:
    """
    The wall clock a stored moment shows on the boundary's zone.

    Reading is what this is for: a plan window lives in the table as UTC, and a
    card that printed it raw would say the training starts at 05:30. The zone
    comes from the same published boundary `local_date()` reads, so nothing here
    is a second opinion about which clock the person lives on.

    Refuses a naive datetime for the reason `local_date()` does — silently
    reading it as UTC would shift the printed hour by the local offset.
    """
    if at.tzinfo is None or at.tzinfo.utcoffset(at) is None:
        raise ValueError(
            "local_time() needs a timezone-aware datetime: a naive one would be "
            f"silently read as UTC and printed off by the local offset. Got {at!r}."
        )
    return at.astimezone(_zone(current_boundary())).time()


def today_local() -> date:
    """
    The day happening right now.

    A wrapper over `local_date()`, not a second rule: it exists so that callers
    do not each write their own `datetime.now(...)` and drift apart on which
    clock they read.
    """
    return local_date(now_utc())


def day_bounds(d: date) -> tuple[datetime, datetime]:
    """
    The half-open UTC interval `[start, end)` of the local day `d`.

    Built for range queries over `timestamptz` columns: a moment `m` satisfies
    `start <= m < end` exactly when `local_date(m) == d`. The interval is 24
    hours of wall clock, which is 23 or 25 real hours on the two days that
    contain a DST transition.

    Assumes the boundary hour is a wall-clock hour that exists on every date in
    the configured zone. It holds for the seeded rule (`Europe/Berlin` switches
    at 02:00/03:00, the day starts at 04:00); a zone that skips the start hour on
    a transition date would need the boundary resolved against the transition
    instead of composed from it.
    """
    boundary = current_boundary()
    zone = _zone(boundary)
    start_hour = time(hour=boundary.day_start_hour)
    start = datetime.combine(d, start_hour, tzinfo=zone)
    end = datetime.combine(d + timedelta(days=1), start_hour, tzinfo=zone)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)
