# [review:need-review] PHASE-02/64-health-vertical-two-metrics
# summary: Health contour tables — metric catalogue and the hourly bucket keyed by (metric, local_date, hour)
from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
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
