# [review:need-review] PHASE-02/64-health-vertical-two-metrics, PHASE-03/238, PHASE-02/68
# summary: Health DTOs — raw-sample intake payload (quantity and category samples, optional sync-run bookkeeping), the metrics-with-daily-values response, the sleep nights response and the sync-status journal view
"""
Wire types of the Health contour.

The intake shape is the contract that keeps the client a pump: it carries raw
samples and nothing derived. There is no field here for an hourly bucket, a
daily total or a sample count, so a client cannot supply one even by accident.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

# A chunk is one week of one device. The bound is a DoS guard: every sample in a
# request is materialised before anything is written.
MAX_SAMPLES_PER_CHUNK = 50_000

# A sync run is one of three kinds; the database stores a plain string, so a
# fourth kind is a change here and nowhere else.
SyncRunKind = Literal["backfill", "rolling", "manual"]
SyncRunStatus = Literal["running", "ok", "failed"]
# The class of a failure, never its text: an exception message is the way a
# metric value reaches the database and, from there, an API response.
SyncFailureKind = Literal["network", "unit", "unknown_metric", "auth", "unknown"]

MAX_DEVICE_ID_LENGTH = 64


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


class HealthCategorySampleIn(BaseModel):
    """
    One HealthKit category sample (sleep, a mindful session): an interval and
    HealthKit's raw category value. For sleep the value is the stage
    (`HKCategoryValueSleepAnalysis`, see `app.health.sleep.SleepStage`).
    """

    identifier: str = Field(
        ...,
        description="HealthKit type identifier, e.g. HKCategoryTypeIdentifierSleepAnalysis",
    )
    value: int = Field(..., description="HealthKit raw category value")
    start: datetime = Field(..., description="Interval start, timezone-aware")
    end: datetime = Field(..., description="Interval end, timezone-aware")
    utc_offset_minutes: int = Field(
        ...,
        ge=-int(18 * 60),
        le=int(18 * 60),
        description="Device UTC offset when the sample was recorded",
    )


class HealthSamplesRequest(BaseModel):
    """One chunk of raw samples. Processed whole or not at all."""

    samples: list[HealthSampleIn] = Field(..., max_length=MAX_SAMPLES_PER_CHUNK)
    # Category types. A chunk carries every interval of each night it touches:
    # the server overwrites a night with what the chunk holds for it.
    category_samples: list[HealthCategorySampleIn] = Field(
        default_factory=list, max_length=MAX_SAMPLES_PER_CHUNK
    )

    # Journal bookkeeping, all optional: a client that sends none of it gets a
    # one-chunk `rolling` run, so the lag still sees it.
    sync_run_id: uuid.UUID | None = Field(
        None, description="Id the device minted for the run; same on every chunk"
    )
    kind: SyncRunKind | None = None
    device_id: str | None = Field(
        None,
        max_length=MAX_DEVICE_ID_LENGTH,
        description="Stable per-install id, not the advertising id",
    )
    chunk_index: int | None = Field(None, ge=0)
    chunks_total: int | None = Field(None, ge=1)
    range_from: date | None = None
    range_to: date | None = None

    @property
    def sample_count(self) -> int:
        return len(self.samples) + len(self.category_samples)

    @model_validator(mode="after")
    def _chunk_bound_covers_both_lists(self) -> HealthSamplesRequest:
        if self.sample_count > MAX_SAMPLES_PER_CHUNK:
            raise ValueError(f"a chunk holds at most {MAX_SAMPLES_PER_CHUNK} samples")
        return self

    @model_validator(mode="after")
    def _run_needs_its_position(self) -> HealthSamplesRequest:
        # A run without a position cannot be counted: the server closes it by
        # the number of distinct chunks it has seen.
        if self.sync_run_id is None:
            return self
        if self.chunk_index is None or self.chunks_total is None:
            raise ValueError("sync_run_id requires chunk_index and chunks_total")
        if self.chunk_index >= self.chunks_total:
            raise ValueError("chunk_index must be below chunks_total")
        return self


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


class HealthMetricDaysResponse(BaseModel):
    """The daily series of one metric over a range, oldest first."""

    identifier: str
    display_name: str
    kind: str
    canonical_unit: str
    days: list[HealthDayValue]


class HealthHourValue(BaseModel):
    """
    One local hour that holds data. `value` is the sum for a cumulative metric and
    the mean for a discrete one; `min`/`max` bound the readings of the hour (equal
    to `value` for an hour with one reading, and for a cumulative metric they are
    the extremes of the pieces that made the sum).
    """

    hour: int
    value: float
    min: float
    max: float
    sample_count: int


class HealthMetricHoursResponse(BaseModel):
    """The hours of one local day; an hour with no data is absent, not zero."""

    identifier: str
    display_name: str
    kind: str
    canonical_unit: str
    date: date
    hours: list[HealthHourValue]


class HealthSleepNightOut(BaseModel):
    """
    One night, named by the local date the person woke up on.

    Minutes per stage count every moment once across iPhone, Watch and apps.
    `bedtime`/`wake_time` carry the offset the device lived at, so "23:40" is
    the string's own clock, not the reader's.
    """

    date: date
    bedtime: datetime
    wake_time: datetime
    in_bed_min: float
    asleep_min: float
    awake_min: float
    core_min: float
    deep_min: float
    rem_min: float
    unspecified_min: float


class HealthSleepResponse(BaseModel):
    """Nights of a date range, oldest first; a night with no data is absent, not zero."""

    nights: list[HealthSleepNightOut]


class HealthSyncFailureIn(BaseModel):
    """A device reporting that a run died, by class. Carries no message field."""

    failure_kind: SyncFailureKind
    kind: SyncRunKind = "rolling"
    device_id: str | None = Field(None, max_length=MAX_DEVICE_ID_LENGTH)
    chunks_total: int | None = Field(None, ge=1)


class HealthSyncRunOut(BaseModel):
    """One journal row as the screen reads it."""

    sync_run_id: uuid.UUID
    kind: SyncRunKind
    status: SyncRunStatus
    # True for a `running` row with no chunk for an hour: the phone left the
    # network mid-run. Derived on read, not stored.
    interrupted: bool
    failure_kind: SyncFailureKind | None
    device_id: str | None
    started_at: datetime
    finished_at: datetime | None
    range_from: date | None
    range_to: date | None
    samples_received: int
    buckets_written: int
    chunks_done: int
    chunks_total: int | None


class HealthSyncStatusResponse(BaseModel):
    """Is the pump alive: the latest run of each kind and how stale the data is."""

    last_runs: list[HealthSyncRunOut]
    last_success_at: datetime | None
    # Hours since the last successful run finished; None when none ever did.
    # Read from the journal, never from the buckets: an empty day is not a lag.
    lag_hours: float | None
    interrupted: bool
