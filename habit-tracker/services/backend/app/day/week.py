# [review:need-review] PHASE-03/94
# summary: pure ISO-week arithmetic — the `2026-W35` code of a date, the Monday..Sunday range one code covers, and the codes a range of dates touches; no clock is read here, "какое сегодня число" stays app.core.daytime
"""
What a week is, decided without a database and without a clock.

A week is named the way `weeks/2026/2026-W35.md` names it — `YYYY-Www`, the ISO
week — and that name is the primary key of the row. So the translation between a
date and its week has to be written exactly once, or the file, the row and the
screen start disagreeing about which Monday a week begins on.

`date.isocalendar()` is the whole of the rule: ISO weeks run Monday to Sunday
and a week belongs to the year that owns its Thursday, which is why 2026-01-01
can legitimately be `2025-W53`. Anything that re-derives that from
`weekday()`/`timedelta` by hand gets those edges wrong.

**No `today` here.** A caller who needs "the current week" asks
`app.core.daytime.today_local()` and passes the date in. The day boundary of
04:00 is that module's business, and a second reading of the clock in this one
would be exactly the split ADR-0014 forbids.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

__all__ = [
    "DAYS_IN_WEEK",
    "BadWeekCode",
    "ISO_CODE_RE",
    "iso_code",
    "week_bounds",
    "week_codes",
]

# Days a week covers. Named because it is the denominator of «0 из 7».
DAYS_IN_WEEK = 7

# `2026-W35`. Anchored on both ends: a code arrives from a URL, and
# `2026-W35-extra` must be refused rather than quietly truncated.
ISO_CODE_RE = re.compile(r"^(\d{4})-W(\d{2})$")

# Width of the zero-padded week field, so `2026-W5` never becomes a second
# spelling of `2026-W05`.
_WEEK_FIELD_WIDTH = 2


class BadWeekCode(ValueError):
    """The string is not an ISO week code, or names a week that does not exist."""


def iso_code(day: date) -> str:
    """
    The ISO week `day` belongs to, as `2026-W35`.

    Zero-padded on purpose: the code is a primary key and a URL segment, and two
    spellings of one week would be two rows.
    """
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:0{_WEEK_FIELD_WIDTH}d}"


def week_bounds(code: str) -> tuple[date, date]:
    """
    The Monday and the Sunday of the week `code` names.

    Raises `BadWeekCode` for a string that is not a week code and for a week
    number that year does not have — 2026 has 53 ISO weeks, 2027 has 52, and
    `2027-W53` is a date that never happened rather than a week with no days.
    """
    match = ISO_CODE_RE.match(code)
    if match is None:
        raise BadWeekCode(
            f"«{code}» не код недели: ожидается YYYY-Www, например 2026-W35."
        )
    year, week = int(match.group(1)), int(match.group(2))
    try:
        monday = date.fromisocalendar(year, week, 1)
    except ValueError as error:
        raise BadWeekCode(f"В {year} году нет недели {week}: {error}") from error
    return monday, monday + timedelta(days=DAYS_IN_WEEK - 1)


def week_codes(start: date, end: date) -> list[str]:
    """
    Every week code the range `[start, end]` touches, oldest first.

    Walks by the day rather than by seven-day steps: a range that begins
    mid-week and ends mid-week touches the weeks on both edges, and stepping by
    weeks from `start` would skip whichever of them the stride jumped over. The
    ranges this is asked about are a screen's worth of days, so the cost is not
    worth an argument.
    """
    if end < start:
        return []
    seen: list[str] = []
    current = start
    while current <= end:
        code = iso_code(current)
        if not seen or seen[-1] != code:
            seen.append(code)
        current += timedelta(days=1)
    return seen
