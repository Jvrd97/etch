# [review:need-review] PHASE-03/165, PHASE-03/220
# summary: database access for Claude Code session aggregates — an upsert on session_uid that a stale restatement cannot roll back, with the day taken from the server's own boundary, the read of a range of days, and (since #220) the day's totals with the count of sessions that ran past the boundary
"""
Database access for the Claude Code session aggregates.

**Агрегат перезаписывается, а не складывается.** A session is appended to all day,
so the agent recomputes it from its first record and sends the whole. The upsert
on `session_uid` takes the restatement as the truth — and refuses it when it ends
earlier than the stored one: a batch delayed by a retry must not turn a longer
session back into a shorter one.

**День сессии — по границе суток сервера.** `local_date` is derived from
`started_at` through `app.core.daytime.local_date`, never taken from the client:
which day a moment belongs to is that module's question alone. A session that
runs across a boundary stays on the day it began.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.daytime import local_date, today_local
from app.models.activity import ClaudeSession
from app.schemas.claude_session import ClaudeSessionIn, ClaudeUsageDayResponse


async def upsert_claude_sessions(
    db: AsyncSession, sessions: list[ClaudeSessionIn]
) -> int:
    """Write the aggregates once per `session_uid`; return how many rows changed."""
    changed = 0
    for item in sessions:
        values = {
            "session_uid": item.session_uid,
            "cwd": item.cwd,
            "git_branch": item.git_branch,
            "local_date": local_date(item.started_at),
            "started_at": item.started_at,
            "ended_at": item.ended_at,
            "assistant_turns": item.assistant_turns,
            "user_turns": item.user_turns,
            "input_tokens": item.input_tokens,
            "output_tokens": item.output_tokens,
            "cache_read_tokens": item.cache_read_tokens,
            "cache_creation_tokens": item.cache_creation_tokens,
            "models": item.models,
            "goal_title": item.goal_title,
            "cli_version": item.cli_version,
        }
        statement = pg_insert(ClaudeSession).values(**values)
        stored = await db.execute(
            statement.on_conflict_do_update(
                index_elements=[ClaudeSession.session_uid],
                set_={
                    **{
                        name: getattr(statement.excluded, name)
                        for name in values
                        if name != "session_uid"
                    },
                    "updated_at": func.now(),
                },
                where=ClaudeSession.ended_at <= statement.excluded.ended_at,
            ).returning(ClaudeSession.id)
        )
        changed += len(stored.all())
    await db.flush()
    return changed


async def list_claude_sessions(
    db: AsyncSession, date_from: date, date_to: date
) -> list[ClaudeSession]:
    """Sessions whose day falls in `[date_from, date_to]`, oldest first."""
    rows = await db.execute(
        select(ClaudeSession)
        .where(ClaudeSession.local_date.between(date_from, date_to))
        .order_by(ClaudeSession.started_at, ClaudeSession.id)
    )
    return list(rows.scalars())


async def claude_usage_for_day(db: AsyncSession, on: date) -> ClaudeUsageDayResponse:
    """Totals of the sessions that began on `on`; a session counts whole on its start day."""
    rows = await list_claude_sessions(db, on, on)
    return ClaudeUsageDayResponse(
        date=on,
        today=today_local(),
        sessions=len(rows),
        assistant_turns=sum(row.assistant_turns for row in rows),
        input_tokens=sum(row.input_tokens for row in rows),
        output_tokens=sum(row.output_tokens for row in rows),
        cache_read_tokens=sum(row.cache_read_tokens for row in rows),
        cache_creation_tokens=sum(row.cache_creation_tokens for row in rows),
        sessions_past_boundary=sum(1 for row in rows if local_date(row.ended_at) > on),
    )
