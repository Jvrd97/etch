# [review:need-review] PHASE-03/164
# summary: wire types of the agent heartbeat — what a mac says about itself (alive, Accessibility, the titles switch, queue depth, last flush, one error code from a closed vocabulary) and what the web reads back (every known agent with the seconds since it was heard and a silent flag against one threshold)
"""
Wire types of the agent heartbeat.

**`last_error` — слово из словаря, не текст.** The field is an enum, so a file
path, a sentence of an exception or a window title is a 422 whoever sent it and
whatever it was meant for. A free string with a length limit would still let a
path in; the vocabulary is the only filter that cannot be argued with. A new
failure the agent can name gets a new member here, in the same commit that makes
the agent send it.

**Момента отчёта в теле нет.** The server stamps `reported_at` with its own
clock: a mac with a wrong date must not be able to look alive or dead, and
«молчит» is measured against the moment the server heard it.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.models.activity import SAMPLING_MAX_SECONDS, SAMPLING_MIN_SECONDS

AGENT_ID_MAX_LENGTH = 64
AGENT_VERSION_MAX_LENGTH = 20
# The width of `agent_heartbeat.last_error`; every code of the vocabulary fits.
LAST_ERROR_MAX_LENGTH = 200


class AgentErrorCode(str, Enum):
    """What the agent may say went wrong. Nothing else can be stored."""

    # The queue dropped intervals: they did not reach the server in time, the
    # catalogue has no such app, or the server refuses the batch for good.
    EXPIRED = "expired"
    UNKNOWN_APP = "unknown_app"
    INVALID_BATCH = "invalid_batch"
    # A send failed: no network, or a server that is down.
    NETWORK = "network"
    # The disk queue could not be opened; the agent keeps intervals in memory.
    QUEUE_UNAVAILABLE = "queue_unavailable"
    # Claude Code logs were read and no record was recognised (ADR-0019).
    CLAUDE_FORMAT = "claude_format"


class AgentHeartbeatIn(BaseModel):
    """What one agent reports about itself, once a minute and after each flush."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1, max_length=AGENT_ID_MAX_LENGTH)
    agent_version: str = Field(min_length=1, max_length=AGENT_VERSION_MAX_LENGTH)
    accessibility_granted: bool
    titles_enabled: bool
    sampling_seconds: int = Field(ge=SAMPLING_MIN_SECONDS, le=SAMPLING_MAX_SECONDS)
    queue_depth: int = Field(ge=0)
    last_flush_at: datetime | None = None
    last_error: AgentErrorCode | None = None


class AgentStatusItem(BaseModel):
    """One known agent as the web shows it."""

    model_config = ConfigDict(from_attributes=True)

    agent_id: str
    agent_version: str
    reported_at: datetime
    accessibility_granted: bool
    titles_enabled: bool
    sampling_seconds: int
    queue_depth: int
    last_flush_at: datetime | None
    last_error: str | None = Field(default=None, max_length=LAST_ERROR_MAX_LENGTH)
    # Seconds since the server last heard this agent, by the server's clock.
    silent_for_seconds: int
    # True once `silent_for_seconds` is past the threshold the response names.
    is_silent: bool


class AgentStatusResponse(BaseModel):
    """Every agent the server has heard of, and the line between alive and silent."""

    agents: list[AgentStatusItem]
    silence_threshold_seconds: int
