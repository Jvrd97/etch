# [review:need-review] PHASE-02/64-health-vertical-two-metrics
# summary: Health contour tables — metric catalogue, the hourly bucket keyed by (metric, local_date, hour) and the sync-run journal
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    ARRAY,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base

if TYPE_CHECKING:
    pass


class HealthMetric(Base):
    """
    One measurable thing Apple Health knows about, described server-side.

    The catalogue is a table rather than an enum in Swift so that teaching the
    app a new metric is a row, not an App Store release: the phone ships whatever
    identifiers it can read and the server decides which ones it accepts.

    `identifier` is HealthKit's own raw string (`HKQuantityTypeIdentifierStepCount`)
    — the only name both sides already agree on.
    """

    __tablename__ = "health_metrics"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    identifier: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    # "cumulative" | "discrete" — see app.health.aggregate.MetricKind. A plain
    # string, not a database enum: widening an enum type costs a migration, and
    # the catalogue is meant to grow by inserts alone.
    kind: Mapped[str] = mapped_column(String(20))
    canonical_unit: Mapped[str] = mapped_column(String(20))
    display_name: Mapped[str] = mapped_column(String(100))
    group: Mapped[str] = mapped_column(String(50), index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    buckets: Mapped[list[HealthHourBucket]] = relationship(
        back_populates="metric", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<HealthMetric(id={self.id}, identifier='{self.identifier}')>"


class HealthHourBucket(Base):
    """
    One local hour of one metric.

    The grain is deliberate: raw samples are hundreds of thousands of rows a year
    and a daily point loses the time-of-day patterns that are the whole bridge to
    the manual records. `local_date`/`hour` are the device's wall clock, so the
    daily fold is a `GROUP BY local_date` with no time conversion on read.

    `sample_count` is what makes the daily average of a discrete metric correct,
    and `min`/`max` keep the extremes the hourly average destroys.
    """

    __tablename__ = "health_hour_buckets"
    __table_args__ = (
        # The natural key, and therefore the whole idempotency story: a re-sent
        # chunk updates these rows instead of adding more.
        UniqueConstraint(
            "metric_id", "local_date", "hour", name="uq_health_hour_bucket_natural_key"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    metric_id: Mapped[int] = mapped_column(
        ForeignKey("health_metrics.id", ondelete="CASCADE"), index=True
    )

    local_date: Mapped[date] = mapped_column(Date, index=True)
    hour: Mapped[int] = mapped_column(Integer)

    value: Mapped[float] = mapped_column(Float)
    sample_count: Mapped[int] = mapped_column(Integer)
    # Attribute names avoid shadowing the builtins in Python while the columns
    # keep the short names the schema was specified with.
    min_value: Mapped[float] = mapped_column("min", Float)
    max_value: Mapped[float] = mapped_column("max", Float)

    # The offset the device was living at. Kept for explaining a bucket back to a
    # human (a flight, a DST night); nothing reads it to compute a value.
    utc_offset_minutes: Mapped[int] = mapped_column(Integer)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    metric: Mapped[HealthMetric] = relationship(back_populates="buckets")

    def __repr__(self) -> str:
        return (
            f"<HealthHourBucket(metric_id={self.metric_id}, "
            f"date={self.local_date}, hour={self.hour}, value={self.value})>"
        )


class HealthSyncRun(Base):
    """
    One run of the pump: a backfill, a rolling top-up or a manual full resync.

    The journal exists because the buckets cannot answer "did the pump run": an
    empty yesterday means either "the sync did not pass" or "the person did not
    move", and those are two different diagnoses. A run is one row however many
    chunks it took; the counters add up as chunks land.

    `kind`, `status` and `failure_kind` are plain strings, not database enums:
    a new run kind (hourly sleep, workouts) is a schema value, not a migration.
    `failure_kind` is a class (`network` | `unit` | `unknown_metric` | `auth` |
    `unknown`) and never an exception text, which is the way a metric value
    leaks into the database and from there into an API response.

    A row with `status='running'` and no activity for an hour is an abandoned
    run — the phone left the network mid-chunk. It has no status of its own:
    the row describes itself, and the reader derives the label.
    """

    __tablename__ = "health_sync_run"
    __table_args__ = (
        Index("ix_health_sync_run_started_at", text("started_at DESC")),
        Index("ix_health_sync_run_kind_started_at", "kind", text("started_at DESC")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # The id the phone minted for the run; every chunk of it carries the same one.
    client_run_id: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True)

    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    failure_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    device_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Last chunk or last state change; what "abandoned" is measured from.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    range_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    range_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    samples_received: Mapped[int] = mapped_column(Integer, default=0)
    buckets_written: Mapped[int] = mapped_column(Integer, default=0)
    chunks_done: Mapped[int] = mapped_column(Integer, default=0)
    # The distinct `chunk_index` values that landed. A chunk the phone re-sends
    # after a timeout the server had already committed is counted once, so a
    # run never closes `ok` on a duplicate.
    chunks_seen: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), default=list, server_default="{}"
    )
    chunks_total: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"<HealthSyncRun(id={self.id}, kind='{self.kind}', status='{self.status}')>"
        )
