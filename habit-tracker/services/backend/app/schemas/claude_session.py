# [review:need-review] PHASE-03/165
# summary: wire types of the Claude Code session aggregates — a session as counters and identifiers only, with extra fields forbidden so message text is refused rather than ignored, a batch capped at 200, and the day listing
"""
Wire types of the Claude Code session metrics.

**Здесь нет поля под текст, и лишнее поле — не «игнорируется», а 422.** The
transcripts hold Talvior code and private conversation; only counters leave the
mac. `extra="forbid"` turns a client that tries to send content (a stale build, a
hand-written `curl`) into a refused request instead of a silently dropped field.
The table has no column for it either (`ClaudeSession`), so the refusal is the
second lock, not the only one — the same device as the write-only
`DailySummaryPlan` in `schemas/daily_summary.py`.

**Сессия присылается целиком каждый раз.** The agent restates the aggregate as the
session grows, and the server overwrites by `session_uid`.
"""

from __future__ import annotations

from datetime import date, timedelta

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

# Потолок пачки. За проход меняются сессии, которых коснулся день, — их десятки;
# двести покрывают первый проход по накопленной истории кусками.
MAX_CLAUDE_SESSIONS_BATCH = 200

# Самый длинный диапазон дней в одном чтении. Блок дня просит один день, неделя —
# предел разумного для экрана; запрос «за всё время» отдаёт тысячи строк.
MAX_LIST_RANGE_DAYS = 92


class ClaudeSessionIn(BaseModel):
    """One session, as the agent restates it."""

    model_config = ConfigDict(extra="forbid")

    session_uid: str = Field(min_length=1, max_length=64)
    cwd: str = Field(max_length=300, description="Каталог проекта, не содержимое")
    git_branch: str | None = Field(default=None, max_length=120)
    started_at: AwareDatetime
    ended_at: AwareDatetime
    assistant_turns: int = Field(ge=0)
    user_turns: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cache_read_tokens: int = Field(ge=0)
    cache_creation_tokens: int = Field(ge=0)
    models: str = Field(default="", max_length=200, description="Через запятую")
    goal_title: str | None = Field(default=None, max_length=200)
    cli_version: str | None = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def _ends_after_it_starts(self) -> ClaudeSessionIn:
        if self.ended_at < self.started_at:
            raise ValueError("ended_at must not be earlier than started_at")
        return self


class ClaudeSessionBatchIn(BaseModel):
    """Sessions in one request."""

    model_config = ConfigDict(extra="forbid")

    sessions: list[ClaudeSessionIn] = Field(
        max_length=MAX_CLAUDE_SESSIONS_BATCH,
        description=f"Не больше {MAX_CLAUDE_SESSIONS_BATCH} сессий за раз",
    )


class ClaudeSessionBatchResponse(BaseModel):
    """How many session rows the batch wrote (a stale restatement writes none)."""

    sessions_written: int


class ClaudeSessionResponse(BaseModel):
    """One stored session."""

    model_config = ConfigDict(from_attributes=True)

    session_uid: str
    cwd: str
    git_branch: str | None
    local_date: date
    started_at: AwareDatetime
    ended_at: AwareDatetime
    assistant_turns: int
    user_turns: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    models: str
    goal_title: str | None
    cli_version: str | None


class ClaudeSessionListResponse(BaseModel):
    """The sessions of a range of days, oldest first."""

    sessions: list[ClaudeSessionResponse]


def check_range(date_from: date, date_to: date) -> None:
    """ValueError for a backwards or oversized range of days."""
    if date_to < date_from:
        raise ValueError("date_to must not be earlier than date_from")
    if date_to - date_from > timedelta(days=MAX_LIST_RANGE_DAYS):
        raise ValueError(f"the range is capped at {MAX_LIST_RANGE_DAYS} days")
