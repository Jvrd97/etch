# [review:need-review] PHASE-03/164
# summary: the heartbeat store — one upsert keyed on agent_id that stamps reported_at with the server's clock, one read of every known agent, and the silence rule (heard longer ago than 30 minutes) kept in a single function
"""
Reads and writes of `agent_heartbeat`.

A heartbeat is stated, not accumulated: the row of an agent is always its last
word, so the write is one upsert and the read is one select however many macs
report.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import AgentHeartbeat
from app.schemas.agent_heartbeat import (
    AgentHeartbeatIn,
    AgentStatusItem,
    AgentStatusResponse,
)

# The agent reports every minute, so half an hour is thirty missed beats: a
# sleeping lid or a restart passes unnoticed, a quit agent does not.
SILENCE_THRESHOLD = timedelta(minutes=30)


def silent_for(reported_at: datetime, now: datetime) -> timedelta:
    """How long ago the server last heard the agent; a future stamp counts as now."""
    return max(now - reported_at, timedelta(0))


def is_silent(reported_at: datetime, now: datetime) -> bool:
    """Silence starts after the threshold, not on it."""
    return silent_for(reported_at, now) > SILENCE_THRESHOLD


async def upsert_heartbeat(
    db: AsyncSession, heartbeat: AgentHeartbeatIn, now: datetime
) -> None:
    """Make the row of `heartbeat.agent_id` say what the agent just said."""
    values = {
        "agent_version": heartbeat.agent_version,
        "reported_at": now,
        "accessibility_granted": heartbeat.accessibility_granted,
        "titles_enabled": heartbeat.titles_enabled,
        "sampling_seconds": heartbeat.sampling_seconds,
        "queue_depth": heartbeat.queue_depth,
        "last_flush_at": heartbeat.last_flush_at,
        "last_error": heartbeat.last_error.value if heartbeat.last_error else None,
    }
    statement = pg_insert(AgentHeartbeat).values(agent_id=heartbeat.agent_id, **values)
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[AgentHeartbeat.agent_id], set_=values
        )
    )
    await db.flush()


async def agent_status(db: AsyncSession, now: datetime) -> AgentStatusResponse:
    """Every known agent, the longest-silent first, judged against `now`."""
    rows = (
        await db.scalars(
            select(AgentHeartbeat).order_by(
                AgentHeartbeat.reported_at, AgentHeartbeat.agent_id
            )
        )
    ).all()
    return AgentStatusResponse(
        agents=[
            AgentStatusItem(
                agent_id=row.agent_id,
                agent_version=row.agent_version,
                reported_at=row.reported_at,
                accessibility_granted=row.accessibility_granted,
                titles_enabled=row.titles_enabled,
                sampling_seconds=row.sampling_seconds,
                queue_depth=row.queue_depth,
                last_flush_at=row.last_flush_at,
                last_error=row.last_error,
                silent_for_seconds=int(
                    silent_for(row.reported_at, now).total_seconds()
                ),
                is_silent=is_silent(row.reported_at, now),
            )
            for row in rows
        ],
        silence_threshold_seconds=int(SILENCE_THRESHOLD.total_seconds()),
    )
