# [review:need-review] PHASE-03/140
# summary: the interval arithmetic behind «ручное > план > ClickUp > git > активность» — merge, subtract and count spans of wall time, plus the rank a source's claim on an hour is settled by; pure, so the rule that decides which source owns a minute is testable with two literals
"""
Which source owns a minute, when two of them claim the same one.

`app.models.role` already publishes the order — `manual`, `plan`, `clickup`,
`git`, `app_usage`, strongest first — as prose beside `ROLE_TIME_SOURCES`. This
module is that order applied to the clock: a weaker source's claim on an hour is
cut down to the part no stronger source claimed, and if nothing is left, it is
not a claim at all.

The whole point is that the day does not add up twice. A section of the plan
saying «Работа 10:00-13:00» and the agent saying «три часа в редакторе за те же
часы» are one three-hour fact reported by two witnesses, not six hours. Summing
them would inflate every day the automation happened to agree with the plan —
and it agrees most on the days the numbers matter.

Deliberately free of the database and of the models. The subtraction is the hard
part and it deserves to be tested with two literals rather than a fixture;
`app.roles.plan_source` (`#140`) and `app.roles.classify` (`#135`) supply the
rows, this module decides which minutes survive.

**Half-open spans.** `[start, end)`, as `tstzrange` stores a plan window: two
spans that touch at 13:00 do not overlap, and an hour counted at the seam would
be counted twice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.models.role import ROLE_TIME_SOURCES

__all__ = [
    "SOURCE_RANK",
    "Span",
    "is_weaker",
    "merge",
    "minutes_of",
    "source_rank",
    "subtract",
]

# Rank of a source: smaller is stronger, exactly as `priority` works for a rule.
# Derived from the tuple rather than restated, because that tuple is already
# documented as being in order of precedence and a second spelling of the order
# is a second thing to keep in step.
SOURCE_RANK: dict[str, int] = {
    source: index for index, source in enumerate(ROLE_TIME_SOURCES)
}

# Where a source nobody has ranked lands: behind everything known. A row written
# by a future importer must not silently displace the plan or a person.
_UNRANKED = len(ROLE_TIME_SOURCES)

# Seconds in a minute — the only unit these spans are ever reported in.
SECONDS_PER_MINUTE = 60


@dataclass(frozen=True)
class Span:
    """
    A piece of wall time, half-open: `[start, end)`.

    Both moments are aware — everything in this service stores `timestamptz` —
    and `end` is strictly later than `start`, which the constructors here
    guarantee by dropping anything that is not.
    """

    start: datetime
    end: datetime

    @property
    def seconds(self) -> float:
        return (self.end - self.start).total_seconds()


def source_rank(source: str) -> int:
    """How strong a source's claim on a minute is; smaller wins."""
    return SOURCE_RANK.get(source, _UNRANKED)


def is_weaker(source: str, than: str) -> bool:
    """Whether `source` loses an hour both of them claim."""
    return source_rank(source) > source_rank(than)


def merge(spans: list[Span]) -> list[Span]:
    """
    The same time, said once: overlapping and touching spans folded together.

    Touching spans are folded as well as overlapping ones (`10:00-11:00` and
    `11:00-12:00` become `10:00-12:00`), because the result is only ever used to
    count minutes and to subtract, and both answers are identical either way
    while one list is shorter.

    Empty and inverted spans are dropped rather than refused: they arrive from a
    subtraction that consumed a span whole, and raising there would make every
    caller handle a case that means «ничего не осталось».
    """
    ordered = sorted(
        (span for span in spans if span.end > span.start), key=lambda s: s.start
    )
    folded: list[Span] = []
    for span in ordered:
        if folded and span.start <= folded[-1].end:
            last = folded[-1]
            if span.end > last.end:
                folded[-1] = Span(start=last.start, end=span.end)
            continue
        folded.append(span)
    return folded


def subtract(spans: list[Span], blockers: list[Span]) -> list[Span]:
    """
    What is left of `spans` once every moment in `blockers` is taken away.

    The answer is merged and in order. A span swallowed whole disappears; a span
    cut in the middle comes back as two, which is the case that makes this a
    function rather than a pair of `max`/`min` calls at the call site: an agent's
    four-hour session with a planned hour in the middle of it is three hours in
    two pieces, and reporting it as one four-hour piece minus sixty minutes would
    put minutes back on the hour the plan already owns.
    """
    taken = merge(blockers)
    if not taken:
        return merge(spans)

    remaining: list[Span] = []
    for span in merge(spans):
        cursor = span.start
        for blocker in taken:
            if blocker.end <= cursor:
                continue
            if blocker.start >= span.end:
                break
            if blocker.start > cursor:
                remaining.append(Span(start=cursor, end=blocker.start))
            cursor = max(cursor, blocker.end)
            if cursor >= span.end:
                break
        if cursor < span.end:
            remaining.append(Span(start=cursor, end=span.end))
    return merge(remaining)


def minutes_of(spans: list[Span]) -> int:
    """
    Whole minutes covered by `spans`, counted after merging.

    Truncating rather than rounding: a fifty-nine-second span is not a minute of
    the day, and rounding it up would let a stream of short focus switches
    manufacture time nobody spent.
    """
    return int(sum(span.seconds for span in merge(spans)) // SECONDS_PER_MINUTE)
