# [review:need-review] PHASE-02/64-health-vertical-two-metrics
# summary: the seeded metric catalogue — the two metrics this vertical carries, one cumulative and one discrete
"""
Seed rows of the metric catalogue.

Two metrics, on purpose. One cumulative (steps) and one discrete (resting heart
rate), because the discrete branch — `sample_count` and the weighted average —
is the part where a mistake is invisible in the numbers afterwards, and leaving
it unexercised until the catalogue is filled out would leave it unverified.

The catalogue grows by inserting rows, not by editing this list: it exists so
that a fresh database and a test database start from the same two metrics.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.health.aggregate import MetricKind


@dataclass(frozen=True)
class MetricSeed:
    identifier: str
    kind: MetricKind
    canonical_unit: str
    display_name: str
    group: str


# Group ids are stable slugs; the screen decides how to title them.
GROUP_MOVEMENT = "movement"
GROUP_HEART = "heart"

SEED_METRICS: tuple[MetricSeed, ...] = (
    MetricSeed(
        identifier="HKQuantityTypeIdentifierStepCount",
        kind=MetricKind.CUMULATIVE,
        canonical_unit="count",
        display_name="Шаги",
        group=GROUP_MOVEMENT,
    ),
    MetricSeed(
        identifier="HKQuantityTypeIdentifierRestingHeartRate",
        kind=MetricKind.DISCRETE,
        canonical_unit="count/min",
        display_name="Пульс покоя",
        group=GROUP_HEART,
    ),
)
