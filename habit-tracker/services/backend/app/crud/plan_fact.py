# [review:need-review] PHASE-03/200
# summary: the plan line as a door into a category's history — the link checked against the catalogue before a plan is stored, a fact written as an ordinary entry of the category (one insert that a replayed or racing request cannot double), corrected in place, deleted only on request, and read back for a whole day in a fixed number of queries together with its total and progress against the target
"""
Facts typed into a plan line, written into the history of its category.

Four decisions are the whole point (ADR-0023).

**A fact is an entry, not a second history.** «Сделал 300» becomes a row of
`entries` with its `entry_values`, in the category the line names, on the day of
the plan. The category screen, its totals and its streak read it the way they
read everything else. The only addition is `entries.plan_item_id`, the line it
was typed into — no foreign key, so a plan replaced at 14:00 neither deletes
history nor loses the link of a line that kept its id.

**The target is not a fact.** `plan_item.target_value` says «300»; nothing is
recorded until a number is typed, a tick of the line records nothing, and 100
typed is 100 stored.

**One key, one entry.** A write carries an `Idempotency-Key`, stored in the same
unique column `POST /entries` uses. The insert is `ON CONFLICT DO NOTHING`, so a
replay after a lost answer and a double tap racing on two connections both end
with the one entry the first write made — the second transaction waits on the
unique index and then reads the winner, without an exception and without a
rollback that would take the rest of the request with it.

**The line reads only what it wrote.** Entries of the same category and day
typed by hand or imported are not rewritten, not summed in, not touched. A
correction edits the entry the line wrote; «Добавить ещё» is a new key and so a
new entry.

PII: every message here is built from ids. Values, names and notes are never
formatted into a message or a log line.
"""

from __future__ import annotations

import math
import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.crud import mark as mark_crud
from app.crud.entry import CHECKED_VALUE, UNCHECKED_VALUE
from app.crud.values import format_number, is_true_value, parse_number
from app.day.plan_links import (
    LINK_OK,
    TARGET_FIELD_TYPES,
    CatalogCategory,
    CatalogField,
    catalog_by_id,
    link_problem,
    link_state,
)
from app.day.plan_validate import PlanRejected
from app.models import Category, Entry, EntryValue, FieldType
from app.models.mark import MARK_DONE
from app.models.plan import DayPlan, PlanItem
from app.schemas.plan_fact import (
    PlanFactEntryResponse,
    PlanFactIn,
    PlanFactValueIn,
    PlanFactValueResponse,
    PlanItemFactsResponse,
    PlanLinkFieldResponse,
    PlanLinkResponse,
    Progress,
    UNMARK,
)

__all__ = [
    "FactInvalid",
    "FactNotFound",
    "FactRefused",
    "FactWrite",
    "LINK_REJECTED",
    "ProposedLink",
    "check_links",
    "correct_fact",
    "day_facts",
    "item_facts",
    "read_catalog",
    "record_fact",
    "remove_fact",
    "to_decimal",
]

# The code of a 422 for a plan whose line names a link that cannot hold a fact.
LINK_REJECTED = "plan_link_invalid"

# A duration travels as whole seconds; this is the only unit it may name.
DURATION_UNIT = "s"


class FactRefused(Exception):
    """
    The line cannot take this fact now: not linked, its link is broken, or the key
    already belongs to a write of another line. A 409 — the request is fine, the
    state it meets is not.
    """

    def __init__(self, error: str, message: str) -> None:
        super().__init__(message)
        self.error = error
        self.message = message


class FactInvalid(Exception):
    """The values do not fit the linked category. A 422 with every reason at once."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


class FactNotFound(LookupError):
    """The entry is not one this line wrote."""


@dataclass(frozen=True)
class FactWrite:
    """What a write did: the entry it touched, and whether it was a replay."""

    entry_id: int
    replayed: bool


@dataclass(frozen=True)
class ProposedLink:
    """A link as a writer of the plan names it, with the line it belongs to."""

    category_id: int | None
    field_id: int | None
    target_value: float | None
    code: str | None = None
    text: str | None = None

    @property
    def is_empty(self) -> bool:
        """The line names no link at all."""
        return (
            self.category_id is None
            and self.field_id is None
            and self.target_value is None
        )


def to_decimal(value: float | None) -> Decimal | None:
    """A target as the column stores it; through `str` so 0.1 stays 0.1."""
    return None if value is None else Decimal(str(value))


def _catalog_entry(category: Category) -> CatalogCategory:
    return CatalogCategory(
        id=category.id,
        name=category.name,
        is_active=category.is_active,
        display_mode=category.display_mode,
        fields=tuple(
            CatalogField(
                id=field.id,
                name=field.name,
                field_type=field.field_type,
                unit=field.unit,
            )
            for field in category.fields
        ),
    )


async def read_catalog(
    db: AsyncSession, category_ids: set[int] | None = None
) -> dict[int, CatalogCategory]:
    """
    Categories with their fields, as plain values: `category_ids`, or all of them.

    One query for the categories and one for their fields, whatever the number of
    lines asking. Archived categories are read too: the reader has to be able to
    say «в архиве» rather than «такой нет».
    """
    if category_ids is not None and not category_ids:
        return {}
    query = select(Category).options(selectinload(Category.fields))
    if category_ids is not None:
        query = query.where(Category.id.in_(category_ids))
    result = await db.execute(query)
    return catalog_by_id(_catalog_entry(row) for row in result.scalars().all())


def _link_reason(link: ProposedLink, catalog: dict[int, CatalogCategory]) -> str | None:
    """Why this proposed link cannot be stored, or None when it can."""
    if link.is_empty:
        return None
    if link.category_id is None:
        return "поле и цель без категории: сначала выберите категорию"
    state = link_state(catalog.get(link.category_id), link.field_id, link.target_value)
    if state == LINK_OK:
        return None
    return link_problem(link.category_id, link.field_id, state)


async def check_links(db: AsyncSession, links: Sequence[ProposedLink]) -> None:
    """
    Refuse the first line whose link cannot hold a fact, naming that line.

    Called before a plan or a line is written, never after: a refused plan leaves
    the stored one as it was. Lines without a link cost nothing — no query is
    made for a plan that names no category.
    """
    named = {link.category_id for link in links if link.category_id is not None}
    if not named and all(link.is_empty for link in links):
        return
    catalog = await read_catalog(db, named)
    for link in links:
        reason = _link_reason(link, catalog)
        if reason is not None:
            raise PlanRejected(
                error=LINK_REJECTED,
                message=f"Связь пункта с категорией не годится: {reason}.",
                code=link.code,
                text=None if link.code else link.text,
            )


async def _linked(
    db: AsyncSession, item: PlanItem
) -> tuple[CatalogCategory, CatalogField]:
    """The category and field this line writes into, or the reason it cannot."""
    if item.category_id is None:
        raise FactRefused("not_linked", f"Пункт {item.id} не связан с категорией.")
    category = (await read_catalog(db, {item.category_id})).get(item.category_id)
    target = None if item.target_value is None else float(item.target_value)
    state = link_state(category, item.field_id, target)
    field = None if category is None else category.field(item.field_id)
    if category is None or field is None or state != LINK_OK:
        raise FactRefused(
            f"link_{state}",
            f"Факт не записан: {link_problem(item.category_id, item.field_id, state)}.",
        )
    return category, field


def _render(
    field: CatalogField, value: PlanFactValueIn
) -> tuple[str | None, str | None]:
    """The value as the EAV column stores it, or the reason it does not fit."""
    if field.field_type is FieldType.BOOLEAN:
        if not isinstance(value.value, bool):
            return None, f"поле {field.id} — галочка: нужно true или false"
        if value.unit is not None:
            return None, f"у галочки {field.id} нет единицы"
        return (CHECKED_VALUE if value.value else UNCHECKED_VALUE), None

    if isinstance(value.value, bool):
        return (
            None,
            f"поле {field.id} — {field.field_type.value}: true/false сюда не пишется",
        )
    number = float(value.value)
    if not math.isfinite(number):
        return None, f"значение поля {field.id} — не число"

    if field.field_type is FieldType.DURATION:
        if value.unit not in (None, DURATION_UNIT):
            return (
                None,
                f"длительность {field.id} передаётся в секундах ({DURATION_UNIT})",
            )
        if number < 0 or not number.is_integer():
            return None, f"длительность {field.id} — целое число секунд не меньше нуля"
        return str(int(number)), None

    if field.field_type is FieldType.NUMBER:
        if value.unit is not None and value.unit.strip() != (field.unit or "").strip():
            return None, f"единица поля {field.id} не совпадает с присланной"
        return format_number(number), None

    return None, f"в поле {field.id} из плана не записать"


def _rendered(
    category: CatalogCategory, values: Iterable[PlanFactValueIn]
) -> dict[int, str]:
    """`{field_id: stored text}` for every value, or every reason they do not fit."""
    reasons: list[str] = []
    rendered: dict[int, str] = {}
    for value in values:
        if value.field_id in rendered:
            reasons.append(f"поле {value.field_id} прислано дважды")
            continue
        field = category.field(value.field_id)
        if field is None:
            reasons.append(
                f"поле {value.field_id} не принадлежит категории {category.id}"
            )
            continue
        text, problem = _render(field, value)
        if problem is not None:
            reasons.append(problem)
        elif text is not None:
            rendered[value.field_id] = text
    if reasons:
        raise FactInvalid(reasons)
    return rendered


async def _keep_mark(
    db: AsyncSession, on: date, item: PlanItem, mark: str | None, source: str
) -> None:
    """
    Put the mark the write asked for, in the same transaction, keeping its note.

    `unmark` takes back only a `done`: the fact no longer backs «сделано», but a
    «не сделал» or «пропустил» was never the fact's to set.
    """
    if mark is None:
        return
    current = await mark_crud.get_mark(db, item.id)
    if mark == UNMARK and (current is None or current.state != MARK_DONE):
        return
    await mark_crud.set_mark(
        db,
        on,
        item.id,
        state=None if mark == UNMARK else mark,
        note=None if current is None else current.note,
        source=source,
    )


async def _entry_by_key(
    db: AsyncSession, key: str
) -> tuple[int, uuid.UUID | None] | None:
    """`(entry id, its line)` already written under `key`, or None."""
    row = (
        await db.execute(
            select(Entry.id, Entry.plan_item_id).where(Entry.idempotency_key == key)
        )
    ).first()
    return None if row is None else (row.id, row.plan_item_id)


def _replay(found: tuple[int, uuid.UUID | None], item: PlanItem) -> FactWrite:
    """The stored write of this key — but only if this line made it."""
    entry_id, plan_item_id = found
    if plan_item_id != item.id:
        raise FactRefused(
            "idempotency_key_spent",
            "Этот Idempotency-Key уже записал другой факт; нужен новый ключ.",
        )
    return FactWrite(entry_id=entry_id, replayed=True)


async def record_fact(
    db: AsyncSession,
    on: date,
    item: PlanItem,
    data: PlanFactIn,
    *,
    idempotency_key: str,
) -> FactWrite:
    """
    Write a new fact of `item` — the first one, or «Добавить ещё».

    A key seen before answers with the entry it wrote, before the link is even
    checked: the request that lost its answer has already been honoured, and an
    archive pressed in between must not turn it into an error. The linked field
    is required; the other fields of a composite category are optional.
    """
    found = await _entry_by_key(db, idempotency_key)
    if found is not None:
        return _replay(found, item)

    category, field = await _linked(db, item)
    rendered = _rendered(category, data.values)
    if field.id not in rendered:
        raise FactInvalid([f"нет значения поля {field.id}, с которым связан пункт"])

    inserted = await db.execute(
        pg_insert(Entry)
        .values(
            category_id=category.id,
            entry_date=data.entry_date or on,
            plan_item_id=item.id,
            idempotency_key=idempotency_key,
        )
        .on_conflict_do_nothing(index_elements=[Entry.idempotency_key])
        .returning(Entry.id)
    )
    entry_id = inserted.scalar_one_or_none()
    if entry_id is None:
        # Another transaction wrote this key between the lookup and the insert,
        # and has committed: the unique index made this one wait for it.
        winner = await _entry_by_key(db, idempotency_key)
        if winner is None:  # pragma: no cover - the conflict above names a row
            raise RuntimeError("idempotency key conflicted with no row")
        return _replay(winner, item)

    db.add_all(
        EntryValue(entry_id=entry_id, field_id=field_id, value=text)
        for field_id, text in rendered.items()
    )
    await db.flush()
    await _keep_mark(db, on, item, data.mark, data.source)
    return FactWrite(entry_id=entry_id, replayed=False)


async def _entry_of_item(
    db: AsyncSession, item: PlanItem, entry_id: int
) -> Entry | None:
    """The entry `entry_id`, but only if this line wrote it."""
    result = await db.execute(
        select(Entry)
        .options(selectinload(Entry.values))
        .where(Entry.id == entry_id, Entry.plan_item_id == item.id)
    )
    return result.scalar_one_or_none()


async def correct_fact(
    db: AsyncSession, on: date, item: PlanItem, entry_id: int, data: PlanFactIn
) -> FactWrite:
    """
    Change a fact this line wrote: 300 becomes 200, not 300 and 200.

    Only the fields sent are rewritten; the rest of the entry stays. An entry of
    another category — the line was re-linked after it was written — is refused
    rather than filled with fields that are not its own.
    """
    entry = await _entry_of_item(db, item, entry_id)
    if entry is None:
        raise FactNotFound(entry_id)
    category, _ = await _linked(db, item)
    if entry.category_id != category.id:
        raise FactRefused(
            "entry_of_another_category",
            f"Запись {entry_id} лежит в другой категории, чем связан пункт.",
        )
    rendered = _rendered(category, data.values)

    stored = {value.field_id: value for value in entry.values}
    for field_id, text in rendered.items():
        if field_id in stored:
            stored[field_id].value = text
        else:
            db.add(EntryValue(entry_id=entry.id, field_id=field_id, value=text))
    if data.entry_date is not None:
        entry.entry_date = data.entry_date
    # The values are rows of their own; the entry is touched explicitly so the
    # history can say when the fact was last changed.
    entry.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await _keep_mark(db, on, item, data.mark, data.source)
    return FactWrite(entry_id=entry.id, replayed=False)


async def remove_fact(
    db: AsyncSession,
    on: date,
    item: PlanItem,
    entry_id: int,
    *,
    mark: str | None,
    source: str,
) -> FactWrite:
    """
    Delete a fact this line wrote — the explicit action, never a side effect.

    Unticking the line does not come here: «снял галочку» and «этого не было» are
    different statements, and only the second one removes history. `mark` is
    `unmark` when what is left no longer makes the line done; it goes in the
    same transaction as the delete.
    """
    entry = await _entry_of_item(db, item, entry_id)
    if entry is None:
        raise FactNotFound(entry_id)
    await db.delete(entry)
    await db.flush()
    await _keep_mark(db, on, item, mark, source)
    return FactWrite(entry_id=entry_id, replayed=False)


def _total(field: CatalogField | None, entries: list[Entry]) -> float | None:
    """The linked field summed over the line's entries; None for a box or nothing."""
    if field is None or field.field_type not in TARGET_FIELD_TYPES:
        return None
    numbers = [
        parse_number(value.value, field_id=field.id, entry_id=entry.id)
        for entry in entries
        for value in entry.values
        if value.field_id == field.id
    ]
    present = [number for number in numbers if number is not None]
    return float(sum(present)) if present else None


def _progress(
    field: CatalogField | None,
    entries: list[Entry],
    total: float | None,
    target: float | None,
    done: bool,
) -> Progress:
    """How the line's facts stand against its target."""
    if not entries:
        return "none"
    if field is not None and field.field_type is FieldType.BOOLEAN:
        return "met" if done else "recorded"
    if field is None or target is None:
        return "recorded"
    return "met" if total is not None and total >= target else "partial"


def _facts_response(
    item: PlanItem, category: CatalogCategory, entries: list[Entry]
) -> PlanItemFactsResponse:
    """One linked line, its entries and how they add up."""
    target = None if item.target_value is None else float(item.target_value)
    field = category.field(item.field_id)
    # A field id the category does not hold is a field that is gone: the
    # foreign key empties the column, and until then the reader says so too.
    state = link_state(category, None if field is None else field.id, target)
    own = [entry for entry in entries if entry.category_id == category.id]
    total = _total(field, own)
    if field is not None and field.field_type is FieldType.BOOLEAN:
        done = any(
            is_true_value(value.value)
            for entry in own
            for value in entry.values
            if value.field_id == field.id
        )
    else:
        done = total is not None and total > 0
    return PlanItemFactsResponse(
        item_id=item.id,
        link=PlanLinkResponse(
            category_id=category.id,
            category_name=category.name,
            category_active=category.is_active,
            field_id=None if field is None else field.id,
            field_name=None if field is None else field.name,
            field_type=None if field is None else field.field_type.value,
            unit=None if field is None else field.unit,
            target_value=target,
            state=state,
            fields=[
                PlanLinkFieldResponse(
                    id=one.id,
                    name=one.name,
                    field_type=one.field_type.value,
                    unit=one.unit,
                )
                for one in category.linkable_fields
            ],
        ),
        entries=[
            PlanFactEntryResponse(
                entry_id=entry.id,
                entry_date=entry.entry_date,
                values=[
                    PlanFactValueResponse(field_id=value.field_id, value=value.value)
                    for value in sorted(entry.values, key=lambda one: one.field_id)
                ],
                created_at=entry.created_at,
                updated_at=entry.updated_at,
            )
            for entry in own
        ],
        total=total,
        done=done,
        progress=_progress(field, own, total, target, done),
    )


async def _facts_for(
    db: AsyncSession, items: Sequence[PlanItem]
) -> list[PlanItemFactsResponse]:
    """
    The facts of every linked line among `items`, in four queries at most.

    Categories with their fields in two, entries with their values in two —
    whether one line is linked or forty. A line whose category is gone reads as
    an ordinary line, which is what `SET NULL` will make of it anyway.
    """
    linked = [item for item in items if item.category_id is not None]
    if not linked:
        return []
    catalog = await read_catalog(
        db, {item.category_id for item in linked if item.category_id is not None}
    )
    result = await db.execute(
        select(Entry)
        .options(selectinload(Entry.values))
        .where(Entry.plan_item_id.in_([item.id for item in linked]))
        .order_by(Entry.entry_date, Entry.id)
        # Re-read rather than trusted from the session: the history screen
        # edits these rows through its own requests.
        .execution_options(populate_existing=True)
    )
    by_item: dict[uuid.UUID, list[Entry]] = defaultdict(list)
    for entry in result.scalars().all():
        if entry.plan_item_id is not None:
            by_item[entry.plan_item_id].append(entry)
    answers: list[PlanItemFactsResponse] = []
    for item in linked:
        category = catalog.get(item.category_id) if item.category_id else None
        if category is not None:
            answers.append(_facts_response(item, category, by_item.get(item.id, [])))
    return answers


async def day_facts(
    db: AsyncSession, plan: DayPlan | None
) -> list[PlanItemFactsResponse]:
    """Every linked line of the day's plan, in the order of the plan."""
    if plan is None:
        return []
    items = [
        item
        for section in sorted(plan.sections, key=lambda row: row.ord)
        for item in sorted(section.items, key=lambda row: row.ord)
    ]
    return await _facts_for(db, items)


async def item_facts(db: AsyncSession, item: PlanItem) -> PlanItemFactsResponse | None:
    """One line's facts, or None when the line is not linked to a category."""
    answers = await _facts_for(db, [item])
    return answers[0] if answers else None
