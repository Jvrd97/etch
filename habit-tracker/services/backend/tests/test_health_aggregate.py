# [review:need-review] PHASE-02/64-health-vertical-two-metrics, PHASE-02/65
# summary: pure aggregation tests — weighted daily fold, local hour buckets, DST merge, and every catalog unit
"""
Unit tests for `app.health.aggregate`. No database, no HTTP: these cover the one
place in the Health contour where an error is invisible after the fact — a daily
number that looks plausible and is wrong.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.health.aggregate import (
    MetricKind,
    RawSample,
    UnitError,
    aggregate_samples,
    canonicalize,
    fold_daily,
)
from app.health.catalog import SEED_METRICS


def utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


class TestFoldDaily:
    """The daily reduction: sum for cumulative, weighted mean for discrete."""

    def test_cumulative_day_is_the_plain_sum(self) -> None:
        assert (
            fold_daily(
                MetricKind.CUMULATIVE, value_sum=1200.0, weighted_sum=0.0, count_sum=7
            )
            == 1200.0
        )

    def test_discrete_day_is_weighted_and_differs_from_the_naive_mean(self) -> None:
        """
        One hour holds a single reading of 60, the next holds nine of 80.

        Weighted: (60*1 + 80*9) / 10 = 78. Naive mean of the two hourly values:
        (60 + 80) / 2 = 70. The gap is the whole point of `sample_count`: an
        average of averages silently over-weights a quiet hour.
        """
        naive_mean = (60.0 + 80.0) / 2

        weighted = fold_daily(
            MetricKind.DISCRETE,
            value_sum=140.0,
            weighted_sum=60.0 * 1 + 80.0 * 9,
            count_sum=10,
        )

        assert weighted == 78.0
        assert weighted != naive_mean

    def test_discrete_day_without_samples_is_none(self) -> None:
        assert (
            fold_daily(
                MetricKind.DISCRETE, value_sum=0.0, weighted_sum=0.0, count_sum=0
            )
            is None
        )


class TestCanonicalize:
    """Units are canonicalised on the way in; the store holds one unit per metric."""

    @pytest.mark.parametrize(
        ("value", "from_unit", "to_unit", "expected"),
        [
            (1.5, "km", "m", 1500.0),
            (100.0, "m", "m", 100.0),
            (1.0, "mi", "m", 1609.344),
            (4.184, "kJ", "kcal", 1.0),
            (2.0, "hr", "min", 120.0),
            (90.0, "s", "min", 1.5),
            (0.05, "s", "ms", 50.0),
            (58.0, "count/min", "count/min", 58.0),
            (58.0, "bpm", "count/min", 58.0),
            (0.97, "fraction", "%", 97.0),
            (1000.0, "g", "kg", 1.0),
            (1.8, "m", "cm", 180.0),
            (7500.0, "count", "count", 7500.0),
        ],
    )
    def test_known_units_convert(
        self, value: float, from_unit: str, to_unit: str, expected: float
    ) -> None:
        assert canonicalize(value, from_unit, to_unit) == pytest.approx(expected)

    @pytest.mark.parametrize(
        "unit",
        sorted({metric.canonical_unit for metric in SEED_METRICS}),
    )
    def test_every_catalog_unit_is_canonical(self, unit: str) -> None:
        assert canonicalize(1.0, unit, unit) == 1.0

    def test_unknown_unit_raises(self) -> None:
        with pytest.raises(UnitError):
            canonicalize(1.0, "furlong", "m")

    def test_unit_from_another_dimension_raises(self) -> None:
        """Steps are not kilograms; a wrong unit must not become a wrong number."""
        with pytest.raises(UnitError):
            canonicalize(70.0, "kg", "m")


class TestAggregateSamples:
    """Raw samples become hourly buckets keyed by the device's local calendar."""

    def test_discrete_hour_holds_mean_count_and_extremes(self) -> None:
        samples = [
            RawSample(
                value=v,
                unit="count/min",
                start=utc(2026, 7, 20, 6, m),
                end=utc(2026, 7, 20, 6, m),
                utc_offset_minutes=120,
            )
            for v, m in ((54.0, 5), (58.0, 20), (62.0, 50))
        ]

        buckets = aggregate_samples(samples, MetricKind.DISCRETE, "count/min")

        assert len(buckets) == 1
        bucket = buckets[0]
        assert (bucket.local_date, bucket.hour) == (date(2026, 7, 20), 8)
        assert bucket.value == pytest.approx(58.0)
        assert bucket.sample_count == 3
        assert (bucket.min_value, bucket.max_value) == (54.0, 62.0)
        assert bucket.utc_offset_minutes == 120

    def test_cumulative_sample_splits_across_local_hour_boundary(self) -> None:
        """
        A 40-minute walk starting at 08:50 local spans two hours: 10 minutes in
        the 08 bucket, 30 in the 09 one. Bucketing it whole by its start would
        move a quarter of the steps into the wrong hour.
        """
        samples = [
            RawSample(
                value=400.0,
                unit="count",
                start=utc(2026, 7, 20, 6, 50),
                end=utc(2026, 7, 20, 7, 30),
                utc_offset_minutes=120,
            )
        ]

        buckets = aggregate_samples(samples, MetricKind.CUMULATIVE, "count")

        assert [(b.hour, b.value) for b in buckets] == [(8, 100.0), (9, 300.0)]
        assert sum(b.value for b in buckets) == 400.0

    def test_local_hour_wins_over_utc_hour(self) -> None:
        """21:30 UTC is 23:30 in Berlin — the bucket follows the lived calendar."""
        samples = [
            RawSample(
                value=120.0,
                unit="count",
                start=utc(2026, 7, 20, 21, 30),
                end=utc(2026, 7, 20, 21, 40),
                utc_offset_minutes=120,
            )
        ]

        buckets = aggregate_samples(samples, MetricKind.CUMULATIVE, "count")

        assert [(b.local_date, b.hour) for b in buckets] == [(date(2026, 7, 20), 23)]

    def test_repeated_dst_hour_merges_into_one_bucket(self) -> None:
        """
        On the night the clocks go back, 02:30 happens twice: once at +02:00 and
        once at +01:00. Both are 02:30 of the same lived date, so they share one
        bucket instead of colliding on the unique key.
        """
        samples = [
            RawSample(
                value=60.0,
                unit="count/min",
                start=utc(2026, 10, 25, 0, 30),
                end=utc(2026, 10, 25, 0, 30),
                utc_offset_minutes=120,
            ),
            RawSample(
                value=70.0,
                unit="count/min",
                start=utc(2026, 10, 25, 1, 30),
                end=utc(2026, 10, 25, 1, 30),
                utc_offset_minutes=60,
            ),
        ]

        buckets = aggregate_samples(samples, MetricKind.DISCRETE, "count/min")

        assert len(buckets) == 1
        assert (buckets[0].local_date, buckets[0].hour) == (date(2026, 10, 25), 2)
        assert buckets[0].sample_count == 2
        assert buckets[0].value == pytest.approx(65.0)

    def test_values_are_canonicalised_before_bucketing(self) -> None:
        samples = [
            RawSample(
                value=1.2,
                unit="km",
                start=utc(2026, 7, 20, 6, 0),
                end=utc(2026, 7, 20, 6, 10),
                utc_offset_minutes=120,
            )
        ]

        buckets = aggregate_samples(samples, MetricKind.CUMULATIVE, "m")

        assert buckets[0].value == pytest.approx(1200.0)

    def test_unknown_unit_stops_the_whole_batch(self) -> None:
        samples = [
            RawSample(
                value=1.0,
                unit="furlong",
                start=utc(2026, 7, 20, 6, 0),
                end=utc(2026, 7, 20, 6, 0),
                utc_offset_minutes=120,
            )
        ]

        with pytest.raises(UnitError):
            aggregate_samples(samples, MetricKind.CUMULATIVE, "m")

    def test_buckets_come_back_in_calendar_order(self) -> None:
        samples = [
            RawSample(
                value=10.0,
                unit="count",
                start=utc(2026, 7, 20, 20, 0) - timedelta(hours=h),
                end=utc(2026, 7, 20, 20, 0) - timedelta(hours=h),
                utc_offset_minutes=0,
            )
            for h in (0, 5, 2)
        ]

        buckets = aggregate_samples(samples, MetricKind.CUMULATIVE, "count")

        assert [b.hour for b in buckets] == [15, 18, 20]
