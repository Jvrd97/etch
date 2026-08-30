# [review:need-review] PHASE-03/88, PHASE-03/90
# summary: wire types of the mark — an explicit target state (null clears it) so that two tabs cannot fight over "the next one", the counts of the day's tasks, and the day's notebook, which now names its source the way a mark does
"""
Wire types of the mark and of the notebook.

**The request names the state, not the step.** `PUT .../marks/{item_id}` takes
`state`, and `null` means "no mark". A body meaning "advance the cycle" would
make the result depend on which of two open tabs arrived first; naming the
target makes the same write twice a no-op and the last writer the winner, which
is exactly the acceptance case. Where the cycle lives — one list, walked by the
browser — is `app.day.marks.MARK_CYCLE`.

**The notebook is one text per day**, and it goes to `journal_entries` rather
than to a table of its own: the day already has a place for prose, and a second
one would mean two answers to "what did I write on the 30th".
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.mark import MARK_SOURCES, MARK_STATES, SOURCE_WEB


class MarkIn(BaseModel):
    """
    The mark a client wants an item to have.

    The vocabulary is checked here rather than left to the CHECK constraint: a
    typo in `state` has to come back as a 422 naming the three words, not as an
    integrity error the caller reads as "the server broke".
    """

    model_config = ConfigDict(extra="forbid")

    state: str | None = Field(
        None,
        description=(
            f"Одно из: {', '.join(MARK_STATES)}. null — снять отметку; "
            "пункт возвращается в «не дошёл»"
        ),
    )
    note: str | None = Field(
        None, description="«Как прошло» — заметка рядом с отметкой"
    )
    source: str = Field(
        SOURCE_WEB, description=f"Кто отметил: {', '.join(MARK_SOURCES)}"
    )

    @field_validator("state")
    @classmethod
    def _known_state(cls, value: str | None) -> str | None:
        if value is not None and value not in MARK_STATES:
            raise ValueError(f"одно из {', '.join(MARK_STATES)} или null")
        return value

    @field_validator("source")
    @classmethod
    def _known_source(cls, value: str) -> str:
        if value not in MARK_SOURCES:
            raise ValueError(f"одно из {', '.join(MARK_SOURCES)}")
        return value


class MarkResponse(BaseModel):
    """
    The mark of one item as it now stands.

    Answers with `state: null` for an item that has no mark rather than with a
    404 or an empty body: "не дошёл" is a state of the line, and the screen that
    just cleared a mark has to be able to render the answer it got.
    """

    model_config = ConfigDict(from_attributes=True)

    item_id: UUID
    state: str | None = Field(
        None, description="done | failed | skipped; null — отметки нет"
    )
    note: str | None = None
    marked_at: datetime | None = Field(
        None, description="Когда поставлено текущее состояние; null — отметки нет"
    )
    updated_at: datetime | None = Field(
        None, description="Последняя запись по этому пункту, чем бы она ни была"
    )
    source: str | None = None


class TaskCountsResponse(BaseModel):
    """
    The day's work tasks, split by what happened to them.

    `skipped` is counted apart from both `done` and `failed`: a task that
    stopped being relevant was neither closed nor missed, and lumping it with
    either would make the header lie in one direction or the other.
    """

    planned: int
    done: int
    failed: int
    skipped: int
    pending: int


class NotebookIn(BaseModel):
    """
    The free text of a day, as the notebook sends it.

    `source` is here for the same reason it is on `MarkIn`: the local agent
    writes the notebook too, and a day the agent wrote into is not a day a
    person came to. Without it `PUT .../notebook` claimed `opened_at` for every
    writer, which is one half of the `#88` debt `#90` pays.
    """

    model_config = ConfigDict(extra="forbid")

    content: str = Field(
        ...,
        description="Текст блокнота целиком; он заменяет прежний, а не дописывается",
    )
    source: str = Field(
        SOURCE_WEB, description=f"Кто записал: {', '.join(MARK_SOURCES)}"
    )

    @field_validator("source")
    @classmethod
    def _known_source(cls, value: str) -> str:
        if value not in MARK_SOURCES:
            raise ValueError(f"одно из {', '.join(MARK_SOURCES)}")
        return value


class NotebookResponse(BaseModel):
    """The day's notebook after the write, read back from `journal_entries`."""

    model_config = ConfigDict(from_attributes=True)

    day_date: date
    content: str
    updated_at: datetime | None = None
