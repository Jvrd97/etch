# [review:need-review] PHASE-03/140
# summary: pure tests of the interval arithmetic behind «ручное > план > ClickUp > git > активность» — the source order, the merge that folds overlapping and touching spans, the subtraction that can cut one span into two, and the truncating minute count
"""
Tests of `app.roles.precedence`.

No database and no fixtures on purpose: the subtraction is the part that decides
whether a day adds up once or twice, and it deserves to be checked with two
literals rather than through a plan and an importer.
"""

from datetime import datetime, timedelta, timezone

from app.models.role import (
    SOURCE_APP_USAGE,
    SOURCE_CLICKUP,
    SOURCE_GIT,
    SOURCE_MANUAL,
    SOURCE_PLAN,
)
from app.roles.precedence import (
    Span,
    is_weaker,
    merge,
    minutes_of,
    subtract,
    source_rank,
)

DAY = datetime(2026, 8, 30, tzinfo=timezone.utc)


def at(hour: float) -> datetime:
    return DAY + timedelta(hours=hour)


def span(start: float, end: float) -> Span:
    return Span(start=at(start), end=at(end))


class TestOrder:
    def test_the_five_sources_rank_the_way_the_adr_names_them(self) -> None:
        """Ручное > план > ClickUp > git > активность, and nothing else decides."""
        order = [
            SOURCE_MANUAL,
            SOURCE_PLAN,
            SOURCE_CLICKUP,
            SOURCE_GIT,
            SOURCE_APP_USAGE,
        ]
        assert [source_rank(source) for source in order] == [0, 1, 2, 3, 4]

    def test_the_agent_loses_to_the_plan_and_the_plan_loses_to_a_person(self) -> None:
        assert is_weaker(SOURCE_APP_USAGE, SOURCE_PLAN)
        assert is_weaker(SOURCE_PLAN, SOURCE_MANUAL)
        assert not is_weaker(SOURCE_MANUAL, SOURCE_APP_USAGE)

    def test_a_source_nobody_ranked_lands_behind_everything_known(self) -> None:
        """A future importer must not silently displace the plan or a person."""
        assert is_weaker("healthkit", SOURCE_APP_USAGE)
        assert not is_weaker(SOURCE_APP_USAGE, "healthkit")


class TestMerge:
    def test_overlapping_spans_become_one(self) -> None:
        assert merge([span(10, 12), span(11, 13)]) == [span(10, 13)]

    def test_touching_spans_become_one(self) -> None:
        assert merge([span(10, 11), span(11, 12)]) == [span(10, 12)]

    def test_a_span_inside_another_disappears_into_it(self) -> None:
        assert merge([span(10, 14), span(11, 12)]) == [span(10, 14)]

    def test_a_gap_is_kept_and_the_answer_is_ordered(self) -> None:
        assert merge([span(13, 14), span(10, 11)]) == [span(10, 11), span(13, 14)]

    def test_an_empty_span_is_dropped_rather_than_refused(self) -> None:
        """It arrives from a subtraction that consumed a span whole."""
        assert merge([span(10, 10)]) == []


class TestSubtract:
    def test_nothing_to_subtract_leaves_the_span_merged(self) -> None:
        assert subtract([span(10, 12)], []) == [span(10, 12)]

    def test_an_overlap_at_the_front_moves_the_start(self) -> None:
        assert subtract([span(10, 13)], [span(9, 11)]) == [span(11, 13)]

    def test_an_overlap_at_the_back_moves_the_end(self) -> None:
        assert subtract([span(10, 13)], [span(12, 15)]) == [span(10, 12)]

    def test_a_blocker_in_the_middle_cuts_the_span_into_two(self) -> None:
        """
        The case that makes this a function rather than a `max`/`min` at the call
        site: a four-hour session with a planned hour inside it is three hours in
        two pieces, and reporting one piece minus sixty minutes would put minutes
        back on the hour the plan already owns.
        """
        assert subtract([span(10, 14)], [span(11, 12)]) == [
            span(10, 11),
            span(12, 14),
        ]

    def test_a_span_swallowed_whole_disappears(self) -> None:
        assert subtract([span(11, 12)], [span(10, 13)]) == []

    def test_a_blocker_that_only_touches_takes_nothing(self) -> None:
        """Half-open spans: `[10,12)` and `[12,13)` do not overlap."""
        assert subtract([span(10, 12)], [span(12, 13)]) == [span(10, 12)]

    def test_several_blockers_are_applied_in_order(self) -> None:
        assert subtract([span(8, 16)], [span(9, 10), span(12, 13)]) == [
            span(8, 9),
            span(10, 12),
            span(13, 16),
        ]


class TestMinutes:
    def test_minutes_are_counted_after_merging(self) -> None:
        assert minutes_of([span(10, 12), span(11, 13)]) == 180

    def test_a_gap_is_not_counted(self) -> None:
        assert minutes_of([span(10, 11), span(13, 14)]) == 120

    def test_a_part_of_a_minute_is_not_a_minute(self) -> None:
        """
        Truncating rather than rounding: a stream of short focus switches must
        not manufacture time nobody spent.
        """
        start = at(10)
        assert minutes_of([Span(start=start, end=start + timedelta(seconds=59))]) == 0

    def test_nothing_is_zero(self) -> None:
        assert minutes_of([]) == 0
