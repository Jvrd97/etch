# [review:need-review] PHASE-03/107
# summary: the single day boundary — local_date()/day_bounds() over APP_TIMEZONE and DAY_START_HOUR; a naive datetime is refused, not assumed to be UTC
"""
The one answer to "which day does this moment belong to".

Nine tickets of this phase attach data to a day, and before this module they
would have answered in two different ways: a versioned `day_start_hour` in one
place, a plain calendar date in `Europe/Berlin` in another. A water mark at
00:30 would then land in one day and a work interval at 00:30 in the previous
one, and a single day screen would show two different "todays".

So there is one rule and one module. A day runs from `DAY_START_HOUR` local
wall clock to the same hour of the next calendar date; a moment at 00:30
belongs to the previous day, everywhere, with no exception for "tracker" data.
Anyone who needs a local date calls `local_date()`; anyone who needs a range
for a SQL query calls `day_bounds()`. A second function of this kind appearing
anywhere in `app/` is a reason to reopen review, not to reconcile the
difference.

**The settings source here is temporary and deliberately narrow.** Until
`day_rule_set` exists (`#86`), the rule is read from `settings.APP_TIMEZONE`
and `settings.DAY_START_HOUR`. `#86` moves the source into that versioned
table *without changing the signature* `local_date(at: datetime) -> date`, so
none of the nine consumers changes a line. That is also why neither function
takes a timezone or a start hour as an argument: an argument would turn the
move of the source into an edit of every call site.

Consumers: `#86` (a moment's day), `#91` (work intervals), `#97` (a signal's
`local_date`), `#121` (quick marks), `#124` (undo), `#127` (challenges),
`#134`/`#135` (role minutes), `#146` (day signals). `compute_streak` still
counts UTC days — a debt named in ADR-0014 and paid by `#90`.

Related: ADR-0014 (day in postgres), ADR-0016 (external inbox), ADR-0018
(challenges and quick marks).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.core.config import settings

__all__ = ["day_bounds", "local_date", "today_local"]


def _zone() -> ZoneInfo:
    """
    The configured IANA zone.

    `ZoneInfo` caches its instances, so this is a dictionary lookup rather than
    a file read, and reading the setting on every call is what lets `#86` swap
    the source without touching callers.
    """
    return ZoneInfo(settings.APP_TIMEZONE)


def local_date(at: datetime) -> date:
    """
    The day the moment `at` belongs to.

    The day starts at `DAY_START_HOUR` local wall clock: 03:59 belongs to the
    previous date, 04:00 to the current one. `at` must be timezone-aware — a
    naive datetime is refused rather than silently read as UTC, because
    "silently read as UTC" is exactly the bug this module exists to prevent.
    """
    if at.tzinfo is None or at.tzinfo.utcoffset(at) is None:
        raise ValueError(
            "local_date() needs a timezone-aware datetime: a naive one has no "
            "single answer and would be silently read as UTC, shifting the day "
            f"by the local offset. Got {at!r}; use "
            "datetime.now(timezone.utc) or attach the origin's tzinfo."
        )
    # Wall-clock arithmetic on purpose: aware datetimes subtract inside their
    # own zone, so this reads the local clock DAY_START_HOUR hours earlier and
    # takes its date. Across a DST transition the intermediate value may carry
    # a stale offset, which does not matter — only `.date()` is used.
    shifted = at.astimezone(_zone()) - timedelta(hours=settings.DAY_START_HOUR)
    return shifted.date()


def today_local() -> date:
    """
    The day happening right now.

    A wrapper over `local_date()`, not a second rule: it exists so that callers
    do not each write their own `datetime.now(...)` and drift apart on which
    clock they read.
    """
    return local_date(datetime.now(timezone.utc))


def day_bounds(d: date) -> tuple[datetime, datetime]:
    """
    The half-open UTC interval `[start, end)` of the local day `d`.

    Built for range queries over `timestamptz` columns: a moment `m` satisfies
    `start <= m < end` exactly when `local_date(m) == d`. The interval is 24
    hours of wall clock, which is 23 or 25 real hours on the two days that
    contain a DST transition.

    Assumes `DAY_START_HOUR` is a wall-clock hour that exists on every date in
    the configured zone. It holds for the default (`Europe/Berlin` switches at
    02:00/03:00, the day starts at 04:00); a zone that skips the start hour on
    a transition date would need the boundary resolved against the transition
    instead of composed from it.
    """
    zone = _zone()
    start_hour = time(hour=settings.DAY_START_HOUR)
    start = datetime.combine(d, start_hour, tzinfo=zone)
    end = datetime.combine(d + timedelta(days=1), start_hour, tzinfo=zone)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)
