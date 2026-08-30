# [review:need-review] PHASE-03/88, PHASE-03/90
# summary: the mark cycle (пусто → done → failed → пусто) and the count of a day's lines by kind — tasks and, since #90, anchors — decided without a database so that "skipped is neither closed nor failed" is one testable sentence written once
"""
What a mark means, decided without a database.

Two rules live here, and both are answers to questions the file-based day could
not answer.

**The cycle is a closed list, not an increment.** A click moves a line пусто →
`done` → `failed` → пусто. `skipped` is deliberately not on that ring: "стало
неактуально" is a judgement about the plan rather than about the work, and a
person who cycles a line four times must not land on it by accident. It is set
explicitly.

**`skipped` is neither closed nor failed.** The counter in the header of the day
counts tasks against the bar of the rule row, and a task that stopped being
relevant is not a task that was done — nor one that was missed. It leaves the
denominator, which is the only reading under which "3 из 3" after a cancelled
meeting is not a lie in either direction.

Nothing here touches the session or the ORM: the truth table is testable in
milliseconds, and `app.crud.mark` calls these functions rather than restating
them in SQL.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from app.day.plan_validate import KIND_ANCHOR, KIND_TASK
from app.models.mark import MARK_DONE, MARK_FAILED, MARK_SKIPPED

__all__ = [
    "MARK_CYCLE",
    "TaskCounts",
    "count_anchors",
    "count_tasks",
    "next_state",
]

# The ring a click walks, `None` being "no mark". Written as data rather than as
# an if-chain because the browser walks the same ring (`lib/marks.ts`) and the
# two have to be comparable by eye.
MARK_CYCLE: tuple[str | None, ...] = (None, MARK_DONE, MARK_FAILED)

# What the header counts against `day_rule_set.max_work_tasks`. The same kind
# `#87` counts against the bar when it accepts the plan — anchors, steps and
# minimums are marked too, and none of them is what "3 из 4" is measuring.
COUNTED_KIND = KIND_TASK

# What the verdict counts as anchors (`#90`). Пункты плана, а не справочник:
# `anchor_kind`/`day_anchor` приезжают с `#92`, and until then the lines of the
# plan are the only place an anchor exists. Все виды весят одинаково — у
# `relationship` нет отдельной причины вердикта, иначе третий приоритет
# оказался бы важнее первых двух.
ANCHOR_KIND = KIND_ANCHOR


def next_state(current: str | None) -> str | None:
    """
    The state one click away from `current`.

    A state outside the ring — `skipped`, or anything a future migration adds —
    returns to пусто. Clicking a line that was set aside has to do something,
    and the only harmless something is to hand it back to the ring.
    """
    if current not in MARK_CYCLE:
        return None
    position = MARK_CYCLE.index(current)
    return MARK_CYCLE[(position + 1) % len(MARK_CYCLE)]


@dataclass(frozen=True)
class TaskCounts:
    """
    The day's work tasks, split by what happened to them.

    `planned` counts every line of that kind, `skipped` included; `done`,
    `failed` and `pending` add up to `planned - skipped`. Kept as four numbers
    rather than a ratio because the screen shows "3 из 4" and `#90`'s verdict
    needs the same four to decide whether the day was won.
    """

    planned: int
    done: int
    failed: int
    skipped: int
    pending: int


def _count(
    kinds: Mapping[uuid.UUID, str], states: Mapping[uuid.UUID, str], of_kind: str
) -> TaskCounts:
    """
    Count the lines of one kind against the marks the plan has.

    Takes two mappings rather than ORM rows so that the rule can be read and
    tested without a session: `kinds` is every item of the plan by id, `states`
    every mark by item id. An item in `states` that is not in `kinds` is
    ignored — a mark whose line has been deleted counts towards nothing.

    Tasks and anchors share this body on purpose: «skipped выходит из
    знаменателя» is one sentence, and a second copy of it would be one edit away
    from the counters disagreeing with the verdict.
    """
    planned = done = failed = skipped = 0
    for item_id, kind in kinds.items():
        if kind != of_kind:
            continue
        planned += 1
        state = states.get(item_id)
        if state == MARK_DONE:
            done += 1
        elif state == MARK_FAILED:
            failed += 1
        elif state == MARK_SKIPPED:
            skipped += 1
    return TaskCounts(
        planned=planned,
        done=done,
        failed=failed,
        skipped=skipped,
        pending=planned - done - failed - skipped,
    )


def count_tasks(
    kinds: Mapping[uuid.UUID, str], states: Mapping[uuid.UUID, str]
) -> TaskCounts:
    """The day's work tasks — what "3 из 4" in the header measures."""
    return _count(kinds, states, COUNTED_KIND)


def count_anchors(
    kinds: Mapping[uuid.UUID, str], states: Mapping[uuid.UUID, str]
) -> TaskCounts:
    """The day's anchors — the edges the verdict weighs before it weighs work."""
    return _count(kinds, states, ANCHOR_KIND)
