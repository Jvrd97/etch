# [review:need-review] PHASE-02/64-health-vertical-two-metrics
# summary: Health DTOs — raw-sample intake payload and the metrics-with-daily-values response
"""
Wire types of the Health contour.

The intake shape is the contract that keeps the client a pump: it carries raw
samples and nothing derived. There is no field here for an hourly bucket, a
daily total or a sample count, so a client cannot supply one even by accident.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

# A chunk is one week of one device. The bound is a DoS guard: every sample in a
# request is materialised before anything is written.
MAX_SAMPLES_PER_CHUNK = 50_000


class HealthSampleIn(BaseModel):
    """One HealthKit sample, exactly as the device read it."""

    identifier: str = Field(
        ...,
        description="HealthKit type identifier, e.g. HKQuantityTypeIdentifierStepCount",
    )
    value: float
    unit: str = Field(
        ..., description="HealthKit unit string, e.g. 'count' or 'count/min'"
    )
    start: datetime = Field(..., description="Sample start, timezone-aware")
    end: datetime = Field(
        ..., description="Sample end; equal to start when instantaneous"
    )
    utc_offset_minutes: int = Field(
        ...,
        ge=-int(18 * 60),
        le=int(18 * 60),
        description="Device UTC offset when the sample was recorded; defines its local hour",
    )


class HealthSamplesRequest(BaseModel):
    """One chunk of raw samples. Processed whole or not at all."""

    samples: list[HealthSampleIn] = Field(..., max_length=MAX_SAMPLES_PER_CHUNK)


class HealthSamplesResponse(BaseModel):
    """What the chunk turned into, so the client can log a sync without guessing."""

    samples_received: int
    buckets_written: int


class HealthDayValue(BaseModel):
    """One day of one metric: summed for cumulative, weighted mean for discrete."""

    date: date
    value: float


class HealthMetricSeries(BaseModel):
    """A catalogue metric with whatever days the requested range holds."""

    identifier: str
    display_name: str
    group: str
    kind: str
    canonical_unit: str
    # Empty for a metric the phone never filled. The app cannot tell a refused
    # permission from an absent measurement, so it says neither.
    days: list[HealthDayValue]


class HealthMetricsResponse(BaseModel):
    metrics: list[HealthMetricSeries]
