# [review:need-review] PHASE-03/87, PHASE-03/88, PHASE-03/93, PHASE-03/147
# summary: plan persistence — a document flattened and judged before a single row is written, the previous plan replaced whole in one transaction (items that re-send their uuid keep it, and their marks are carried across the replace), overlapping windows found by a self-join on `&&` rather than on render, and every goal of the quarter the document names looked up in one query so a link to a goal that does not exist is a 422 naming the task rather than a 500 naming a foreign key
"""
Database access for the plan of a day.

The order of operations here is the design, not an implementation detail.

**Flatten, then judge, then write.** The document is walked once into a flat
list of prepared rows — windows resolved against the day boundary, markdown
flattened, `ord` assigned from position — and only that list is handed to
`app.day.plan_validate`. Judging the JSON directly would mean the validator and
the writer each parse a window, and the day a plan is accepted with one reading
and stored with another is the day the constraint stops meaning anything.

**A plan replaces a plan.** A second `POST` on the same date deletes the old
rows and writes the new ones inside one transaction. Merging would leave the
caller unable to say what the plan *is* without replaying every edit, and
`day_plan.day_date` is unique precisely so that no code path can end up with
two.

**Overlaps are a query, not a render.** Two windows intersect if the database
says so — a self-join on `&&` over the GiST index on the generated `window`
column. The screen is then one consumer of that fact rather than its only
owner, and `#90`'s verdict can ask the same question without reimplementing it.

**A re-sent uuid means "the same line".** An incoming item may carry the `id` it
already has; when that id belongs to the plan currently stored for this date, the
row keeps it and its mark is carried across the replace. That is what makes
"поправил формулировку задачи" different from "выкинул задачу и завёл новую" —
under `#88` the first must not un-tick anything, and position cannot express the
difference (it was position that made the file-based marks slide onto the wrong
lines in the first place). An id from another day, or one nobody has seen, is
not honoured: a stale id would otherwise collide with a live row from a day the
caller was not editing.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.daytime import DayBoundary, current_boundary, local_time
from app.day.constraints import DraftItem, PlanDraft
from app.crud import goal as goal_crud
from app.crud import mark as mark_crud
from app.day.plan_validate import (
    ItemFacts,
    PlanRejected,
    check_goal_exists,
    check_hard_rigidity,
    check_item_shape,
    check_task_bar,
    parse_window,
    resolve_window,
    to_plain,
    validate_plan,
)
from app.models.day import DayRuleSet
from app.crud import plan_revision as revision_crud
from app.models.plan import EDITED_BY_HUMAN, DayPlan, PlanItem, PlanSection
from app.models.plan_revision import (
    AUTHOR_HUMAN,
    FIELD_ORD,
    FIELD_SECTION_ID,
    FIELD_STATUS,
    FIELD_TEXT,
    FIELD_WINDOW_END,
    FIELD_WINDOW_START,
)
from app.schemas.plan import (
    PlanDocument,
    PlanItemCreate,
    PlanItemIn,
    PlanItemMove,
    PlanItemPatch,
    PlanItemResponse,
    PlanResponse,
    PlanSectionResponse,
    ScheduleEntry,
    ScheduleOverlap,
)

SECONDS_PER_MINUTE = 60

# Two windows overlap when the stored ranges intersect. `tstzrange` is half-open,
# so 09:00-10:00 and 10:00-11:00 touch without overlapping — which is the answer
# a reader wants, and the reason this is a range operator rather than a pair of
# comparisons somebody would have got wrong at the boundary. `left` is the item
# that starts earlier, so the pair reads in the order of the day.
OVERLAP_SQL = text(
    """
    SELECT
        a.id AS left_item_id,
        b.id AS right_item_id,
        EXTRACT(EPOCH FROM (
            upper(a.window * b.window) - lower(a.window * b.window)
        ))::bigint AS overlap_seconds
    FROM plan_item a
    JOIN plan_section sa ON sa.id = a.section_id
    JOIN plan_item b ON b.window && a.window
    JOIN plan_section sb ON sb.id = b.section_id
    WHERE sa.plan_id = :plan_id
      AND sb.plan_id = :plan_id
      AND (a.starts_at, a.id) < (b.starts_at, b.id)
    ORDER BY a.starts_at, b.starts_at
    """
)


@dataclass
class _PreparedItem:
    """
    One row as it will be written, with everything already decided.

    Carries its own `id` before the insert so that a child can name its parent
    without a second round trip, and so that a rejection can point at a line the
    caller sent rather than at a row that was never created.
    """

    id: uuid.UUID
    section_index: int
    parent_id: uuid.UUID | None
    ord: int
    source: PlanItemIn
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    text_plain: str = ""
    children: list[_PreparedItem] = field(default_factory=list)

    def facts(self) -> ItemFacts:
        """What `app.day.plan_validate` needs in order to judge this line."""
        return ItemFacts(
            kind=self.source.kind,
            rigidity=self.source.rigidity,
            code=self.source.code,
            text_plain=self.text_plain,
            has_window=self.starts_at is not None and self.ends_at is not None,
            has_criterion=bool(self.source.done_criterion),
            is_goal_linked=(
                self.source.quarter_goal_id is not None
                or bool(self.source.unlinked_reason)
            ),
            quarter_goal_id=self.source.quarter_goal_id,
        )


def _identity(
    item: PlanItemIn, keep: frozenset[uuid.UUID], taken: set[uuid.UUID]
) -> uuid.UUID:
    """
    The uuid this line will be stored under.

    A client that sends back an id already in this day's plan is saying "this is
    the same line" and gets to keep it, marks and all. Anything else — no id, an
    id from another day, an invented one — gets a fresh uuid, because honouring
    it could collide with a live row elsewhere.

    The same id twice in one document is refused rather than silently split: two
    lines claiming to be the same line have one mark between them, and guessing
    which of them owns it is exactly the class of mistake `#88` exists to end.
    """
    if item.id is None or item.id not in keep:
        return uuid.uuid4()
    if item.id in taken:
        raise PlanRejected(
            error="duplicate_item_id",
            message=(
                f"Пункт с id {item.id} встречается в плане дважды. Один id — один "
                "пункт: у второго пункта id должен быть свой или отсутствовать."
            ),
            code=item.code,
            text=to_plain(item.text_md),
        )
    taken.add(item.id)
    return item.id


def _prepare_items(
    items: list[PlanItemIn],
    section_index: int,
    parent_id: uuid.UUID | None,
    on: date,
    boundary: DayBoundary,
    flat: list[_PreparedItem],
    keep: frozenset[uuid.UUID],
    taken: set[uuid.UUID],
) -> list[_PreparedItem]:
    """
    Walk one level of the document, resolving every window as it goes.

    `ord` is the position in the list, per level: siblings are numbered among
    themselves, so inserting a step into a training block does not renumber the
    section below it.
    """
    prepared: list[_PreparedItem] = []
    for index, item in enumerate(items):
        row = _PreparedItem(
            id=_identity(item, keep, taken),
            section_index=section_index,
            parent_id=parent_id,
            ord=index,
            source=item,
            text_plain=to_plain(item.text_md),
        )
        if item.window is not None:
            start, end = parse_window(item.window)
            window = resolve_window(on, start, end, boundary)
            row.starts_at = window.starts_at
            row.ends_at = window.ends_at
        prepared.append(row)
        flat.append(row)
        row.children = _prepare_items(
            item.children, section_index, row.id, on, boundary, flat, keep, taken
        )
    return prepared


def prepare_plan(
    document: PlanDocument,
    on: date,
    boundary: DayBoundary,
    keep: frozenset[uuid.UUID] = frozenset(),
) -> tuple[list[list[_PreparedItem]], list[_PreparedItem]]:
    """
    The document as rows-to-be: one tree per section, plus every row flat.

    The flat list is what gets judged; the trees are what gets written. Both
    reference the same objects, so a line cannot be validated in one shape and
    stored in another.

    `keep` is the set of ids the day already has: an incoming id from that set
    is honoured, everything else gets a fresh one. Empty by default, so a caller
    that only wants to know what a document *would* become — a preview, a test
    — mints new ids and touches nothing.
    """
    trees: list[list[_PreparedItem]] = []
    flat: list[_PreparedItem] = []
    taken: set[uuid.UUID] = set()
    for section_index, section in enumerate(document.sections):
        trees.append(
            _prepare_items(
                section.items, section_index, None, on, boundary, flat, keep, taken
            )
        )
    return trees, flat


async def _stored_item_ids(db: AsyncSession, on: date) -> frozenset[uuid.UUID]:
    """
    Ids of every item currently stored for `on`.

    Read as bare ids rather than as entities: this runs before a delete, and an
    ORM object loaded here would still be in the identity map when the row is
    inserted again under the same primary key.
    """
    result = await db.execute(
        select(PlanItem.id)
        .join(PlanSection, PlanSection.id == PlanItem.section_id)
        .join(DayPlan, DayPlan.id == PlanSection.plan_id)
        .where(DayPlan.day_date == on)
    )
    return frozenset(result.scalars().all())


async def get_plan(db: AsyncSession, on: date) -> DayPlan | None:
    """The stored plan of `on`, with sections and items loaded, or None."""
    result = await db.execute(
        select(DayPlan)
        .where(DayPlan.day_date == on)
        .options(selectinload(DayPlan.sections).selectinload(PlanSection.items))
    )
    return result.scalar_one_or_none()


async def delete_plan(db: AsyncSession, on: date) -> bool:
    """
    Remove the plan of `on` entirely. Sections and items go with it by cascade.

    Returns whether there was one, so the caller can tell "replaced" from
    "created" without a second query.
    """
    result = await db.execute(delete(DayPlan).where(DayPlan.day_date == on))
    await db.flush()
    return bool(result.rowcount)


async def replace_plan(
    db: AsyncSession,
    on: date,
    rule: DayRuleSet,
    document: PlanDocument,
    boundary: DayBoundary | None = None,
    author: str = AUTHOR_HUMAN,
    *,
    report_id: uuid.UUID | None = None,
    model: str | None = None,
    prompt_hash: str | None = None,
) -> DayPlan:
    """
    Store `document` as the plan of `on`, replacing whatever was there.

    **Запись документа целиком режет ревизию** (`#150`). Это генерация, чьей бы
    она ни была: план заменён, а не поправлен, и «что предлагали до этого»
    сохраняется только снимком. Первая ревизия дня получает номер 0 — она и есть
    предложение машины, если писал скелет (`author='fallback'`) или модель.
    Правка по одному пункту ревизии не режет — она пишет журнал.

    Raises `PlanRejected` before touching a row: nothing is deleted for a plan
    that is not going to be accepted, so a rejected `POST` leaves yesterday's
    plan exactly as it was rather than emptying the day on the way to a 422.

    Items whose ids the document sent back keep those ids, and their marks are
    lifted over the delete and put back. Everything else is a new line with a
    new id and no mark — including a line whose text is identical to one that
    was there, because a plan that re-mints its ids is a plan that is being
    rewritten rather than edited.
    """
    resolved_boundary = boundary if boundary is not None else current_boundary()
    keep = await _stored_item_ids(db, on)
    trees, flat = prepare_plan(document, on, resolved_boundary, keep)
    facts = [row.facts() for row in flat]
    # One query for every goal the document names, header included. The rule
    # itself stays in `plan_validate`, which has no session: this is the layer
    # that is allowed to read, and it reads once.
    named = {fact.quarter_goal_id for fact in facts if fact.quarter_goal_id is not None}
    if document.quarter_goal_id is not None:
        named.add(document.quarter_goal_id)
    known = await goal_crud.existing_goal_ids(db, named)
    validate_plan(facts, rule, known, document.quarter_goal_id)

    carried = await mark_crud.snapshot_marks(
        db, {row.id for row in flat if row.id in keep}
    )
    await delete_plan(db, on)

    plan = DayPlan(
        id=uuid.uuid4(),
        day_date=on,
        title=document.title,
        title_marker=document.title_marker,
        lede=document.lede,
        purpose_md=document.purpose_md,
        quarter_goal_id=document.quarter_goal_id,
        counters=document.counters,
        condition_tomorrow=document.condition_tomorrow,
        status=document.status,
        source=document.source,
        raw_md=document.raw_md,
    )
    db.add(plan)

    for section_index, section_in in enumerate(document.sections):
        section = PlanSection(
            id=uuid.uuid4(),
            plan_id=plan.id,
            ord=section_index,
            title=section_in.title,
            kind=section_in.kind,
        )
        db.add(section)
        for row in flat:
            if row.section_index == section_index:
                db.add(_to_model(row, section.id))

    await db.flush()
    await mark_crud.restore_marks(db, carried)
    stored = await get_plan(db, on)
    if stored is None:  # pragma: no cover - the insert above just ran
        raise RuntimeError(
            f"plan for {on.isoformat()} vanished between insert and read."
        )
    await revision_crud.cut_revision(
        db,
        on,
        stored,
        author,
        report_id=report_id,
        model=model,
        prompt_hash=prompt_hash,
    )
    return stored


def _to_model(row: _PreparedItem, section_id: uuid.UUID) -> PlanItem:
    """One prepared row as the ORM object that will be inserted."""
    source = row.source
    return PlanItem(
        id=row.id,
        section_id=section_id,
        parent_id=row.parent_id,
        ord=row.ord,
        kind=source.kind,
        rigidity=source.rigidity,
        text_md=source.text_md,
        text_plain=row.text_plain,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        window_comment=source.window_comment,
        code=source.code,
        done_criterion=source.done_criterion,
        why_md=source.why_md,
        plan_md=source.plan_md,
        external_ref=source.external_ref,
        extra=source.extra,
        quarter_goal_id=source.quarter_goal_id,
        unlinked_reason=source.unlinked_reason,
        quick_mark_id=source.quick_mark_id,
        carried_from_item_id=source.carried_from_item_id,
        carry_count=source.carry_count,
        legacy_key=source.legacy_key,
    )


async def find_overlaps(db: AsyncSession, plan_id: uuid.UUID) -> list[ScheduleOverlap]:
    """Every pair of items of this plan whose windows intersect."""
    result = await db.execute(OVERLAP_SQL, {"plan_id": plan_id})
    return [
        ScheduleOverlap(
            left_item_id=row.left_item_id,
            right_item_id=row.right_item_id,
            overlap_minutes=int(row.overlap_seconds) // SECONDS_PER_MINUTE,
        )
        for row in result
    ]


def build_schedule(plan: DayPlan) -> list[ScheduleEntry]:
    """
    Every item that claimed a piece of the clock, in the order of the day.

    Minutes are computed here rather than in the browser: a window that runs
    past midnight is only sixty minutes long to someone who knows where the day
    ends, and the stored moments already carry that answer.
    """
    entries: list[ScheduleEntry] = []
    for section in plan.sections:
        for item in section.items:
            if item.starts_at is None or item.ends_at is None:
                continue
            span = item.ends_at - item.starts_at
            entries.append(
                ScheduleEntry(
                    item_id=item.id,
                    section_id=section.id,
                    code=item.code,
                    text_plain=item.text_plain,
                    kind=item.kind,
                    rigidity=item.rigidity,
                    starts_at=item.starts_at,
                    ends_at=item.ends_at,
                    minutes=int(span.total_seconds()) // SECONDS_PER_MINUTE,
                    window_comment=item.window_comment,
                )
            )
    entries.sort(key=lambda entry: (entry.starts_at, entry.ends_at))
    return entries


def _item_response(item: PlanItem) -> PlanItemResponse:
    """
    One row as its DTO, field by field and with no children yet.

    Spelled out rather than left to `model_validate(item)`: pydantic would read
    every attribute the DTO declares, `children` included, and reading that one
    off an ORM object outside a greenlet is a lazy load that raises. Naming the
    columns also means adding a column to the table does not silently add a
    field to the wire.
    """
    return PlanItemResponse(
        id=item.id,
        parent_id=item.parent_id,
        ord=item.ord,
        kind=item.kind,
        rigidity=item.rigidity,
        text_md=item.text_md,
        text_plain=item.text_plain,
        starts_at=item.starts_at,
        ends_at=item.ends_at,
        window_comment=item.window_comment,
        code=item.code,
        done_criterion=item.done_criterion,
        why_md=item.why_md,
        plan_md=item.plan_md,
        external_ref=item.external_ref,
        extra=dict(item.extra),
        quarter_goal_id=item.quarter_goal_id,
        unlinked_reason=item.unlinked_reason,
        quick_mark_id=item.quick_mark_id,
        carried_from_item_id=item.carried_from_item_id,
        carry_count=item.carry_count,
        children=[],
    )


def _nest(items: list[PlanItem]) -> list[PlanItemResponse]:
    """
    The flat rows of a section rebuilt into the tree they were sent as.

    Two passes, not one. `ord` numbers siblings among themselves, so a child at
    position 0 sorts ahead of its parent at position 2 and a single pass would
    hand the child a parent it has not built yet — and quietly promote it to a
    root, which reads on screen as a step that escaped its task.
    """
    ordered = sorted(items, key=lambda row: row.ord)
    by_id: dict[uuid.UUID, PlanItemResponse] = {}
    for item in ordered:
        by_id[item.id] = _item_response(item)

    roots: list[PlanItemResponse] = []
    for item in ordered:
        node = by_id[item.id]
        parent = by_id.get(item.parent_id) if item.parent_id else None
        if parent is None:
            roots.append(node)
        else:
            parent.children.append(node)
    return roots


async def to_response(db: AsyncSession, plan: DayPlan) -> PlanResponse:
    """The stored plan as the screen and `/day-open` read it."""
    sections = [
        PlanSectionResponse(
            id=section.id,
            ord=section.ord,
            title=section.title,
            kind=section.kind,
            items=_nest(list(section.items)),
        )
        for section in sorted(plan.sections, key=lambda row: row.ord)
    ]
    return PlanResponse(
        id=plan.id,
        day_date=plan.day_date,
        title=plan.title,
        title_marker=plan.title_marker,
        lede=plan.lede,
        purpose_md=plan.purpose_md,
        quarter_goal_id=plan.quarter_goal_id,
        counters=list(plan.counters),
        condition_tomorrow=plan.condition_tomorrow,
        status=plan.status,
        source=plan.source,
        needs_review=plan.needs_review,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
        sections=sections,
        schedule=build_schedule(plan),
        overlaps=await find_overlaps(db, plan.id),
    )


class PlanItemNotFound(LookupError):
    """Пункта с таким id нет в плане запрошенного дня."""


class PlanSectionNotFound(LookupError):
    """Секции с таким id нет в плане запрошенного дня."""


# --- Правка одного пункта (#110) ------------------------------------------
#
# Замена плана целиком отсюда не вызывается и не подменяется: `replace_plan` —
# операция генератора, она сносит план и кладёт новый, а человеку нужна
# противоположная — при которой `plan_item.id` переживает правку вместе с
# отметкой `#88`.


# Имя ограничения в базе → машинный код правила и его формулировка. Отказ базы
# обязан выглядеть так же, как отказ документа: код правила и пункт, а не
# «validation error» и имя constraint, которого нет ни в одном тексте канона.
CONSTRAINT_RULES: dict[str, tuple[str, str]] = {
    "ck_plan_item_task_has_window_and_criterion": (
        "task_without_window_or_criterion",
        "у задачи должны быть окно и критерий «Сделано». Задача без них — "
        "не задача, а пожелание.",
    ),
    "ck_plan_item_free_has_no_window": (
        "free_item_has_window",
        "пункт свободного блока не может иметь окна: свободный вечер на то и "
        "свободный, что расписанию в нём места нет.",
    ),
    "ck_plan_item_task_is_linked_or_explained": (
        "task_is_not_linked_or_explained",
        "задача называет либо цель квартала, либо причину, по которой цели "
        "нет. Молча чужая срочность в план не попадает.",
    ),
    "ck_plan_item_window_is_forward": (
        "window_is_not_forward",
        "окно кончается раньше, чем начинается.",
    ),
    "ck_plan_item_kind": ("unknown_item_kind", "неизвестный вид пункта."),
    "ck_plan_item_rigidity": ("unknown_rigidity", "неизвестная жёсткость пункта."),
    "ck_plan_item_edited_by": ("unknown_editor", "неизвестный автор правки."),
    "uq_plan_item_position": (
        "duplicate_position",
        "два пункта заняли одно место в секции.",
    ),
    "fk_plan_item_quarter_goal_id": (
        "quarter_goal_missing",
        "цели квартала с таким id нет.",
    ),
}

# Поля патча, которые кладутся в колонку под тем же именем. `window` в списке
# нет: оно приезжает строкой «ЧЧ:ММ-ЧЧ:ММ» и разворачивается в две колонки.
PATCH_COLUMNS: tuple[str, ...] = (
    "kind",
    "rigidity",
    "text_md",
    "window_comment",
    "code",
    "done_criterion",
    "why_md",
    "plan_md",
    "external_ref",
    "extra",
    "quarter_goal_id",
    "unlinked_reason",
    "quick_mark_id",
)


def _reject_from_db(error: IntegrityError) -> PlanRejected:
    """
    Отказ базы, переведённый на язык правил канона.

    Ищется по имени ограничения в тексте ошибки: asyncpg кладёт его туда, а
    разбирать приватные поля драйвера значило бы привязаться к его версии.
    Неизвестное имя даёт общий код — молчаливого 500 не остаётся.
    """
    text_of = str(error.orig) if error.orig is not None else str(error)
    for name, (code, message) in CONSTRAINT_RULES.items():
        if name in text_of:
            return PlanRejected(error=code, message=f"Правка отклонена: {message}")
    return PlanRejected(
        error="plan_item_rejected",
        message="Правка отклонена базой: она нарушает правило плана.",
    )


async def _level(
    db: AsyncSession, section_id: uuid.UUID, parent_id: uuid.UUID | None
) -> list[PlanItem]:
    """Братья одного уровня по возрастанию `ord`; уровень — секция плюс родитель."""
    condition = (
        PlanItem.parent_id.is_(None)
        if parent_id is None
        else PlanItem.parent_id == parent_id
    )
    result = await db.execute(
        select(PlanItem)
        .where(PlanItem.section_id == section_id, condition)
        .order_by(PlanItem.ord, PlanItem.created_at)
    )
    return list(result.scalars().all())


async def _renumber(
    db: AsyncSession,
    section_id: uuid.UUID,
    parent_id: uuid.UUID | None,
    order: list[PlanItem] | None = None,
) -> None:
    """
    Перенумеровать уровень в 0…n−1 одной транзакцией.

    Дыры и дубли `ord` не «почти незаметны»: по `ord` строится и порядок на
    экране, и вложенность в ответе, и уникальное ограничение позиции. Поэтому
    перестановка не правит один `ord`, а переписывает уровень целиком —
    промежуточное состояние с дублями законно, потому что ограничение отложено
    до коммита.
    """
    rows = order if order is not None else await _level(db, section_id, parent_id)
    for position, row in enumerate(rows):
        if row.ord != position:
            row.ord = position
    await db.flush()


async def _item_of_day(
    db: AsyncSession, on: date, item_id: uuid.UUID
) -> PlanItem | None:
    """Пункт `item_id`, но только если он в плане дня `on`."""
    result = await db.execute(
        select(PlanItem)
        .join(PlanSection, PlanSection.id == PlanItem.section_id)
        .join(DayPlan, DayPlan.id == PlanSection.plan_id)
        .where(DayPlan.day_date == on, PlanItem.id == item_id)
    )
    return result.scalar_one_or_none()


async def _section_of_day(
    db: AsyncSession, on: date, section_id: uuid.UUID
) -> PlanSection | None:
    """Секция `section_id`, но только если она в плане дня `on`."""
    result = await db.execute(
        select(PlanSection)
        .join(DayPlan, DayPlan.id == PlanSection.plan_id)
        .where(DayPlan.day_date == on, PlanSection.id == section_id)
    )
    return result.scalar_one_or_none()


def _apply_window(
    item: PlanItem, window: str | None, on: date, boundary: DayBoundary
) -> None:
    """Развернуть окно «ЧЧ:ММ-ЧЧ:ММ» в две колонки; `None` — снять окно."""
    if window is None:
        item.starts_at = None
        item.ends_at = None
        return
    start, end = parse_window(window)
    resolved = resolve_window(on, start, end, boundary)
    item.starts_at = resolved.starts_at
    item.ends_at = resolved.ends_at


async def edit_item(
    db: AsyncSession,
    on: date,
    item_id: uuid.UUID,
    patch: PlanItemPatch,
    editor: str = EDITED_BY_HUMAN,
    boundary: DayBoundary | None = None,
) -> PlanItem:
    """
    Правка одного пункта: только присланные поля, id и отметка на месте.

    `PlanItemNotFound` — пункта нет в плане этого дня. `PlanRejected` — база не
    пустила: это единственный источник отказа для правки человека, потому что
    правила документа человеку не запрещают, а предупреждают (`human_warnings`).
    """
    item = await _item_of_day(db, on, item_id)
    if item is None:
        raise PlanItemNotFound(item_id)

    before = _journalled(item)
    fields = patch.model_dump(exclude_unset=True)
    for name in PATCH_COLUMNS:
        if name in fields:
            setattr(item, name, fields[name])
    if "text_md" in fields:
        item.text_plain = to_plain(item.text_md)
    if "window" in fields:
        _apply_window(
            item,
            fields["window"],
            on,
            boundary if boundary is not None else current_boundary(),
        )
    item.edited_by = editor
    item.updated_at = datetime.now(timezone.utc)
    try:
        await _check_row_rules(db, item)
    except PlanRejected:
        # Отвергнутая правка не должна дожить до чужого `flush`: объект в
        # сессии всё ещё несёт её, и следующая запись в той же транзакции
        # унесла бы её в базу. `expire` забывает изменения вместе с состоянием.
        db.expire(item)
        raise
    try:
        await db.flush()
    except IntegrityError as error:
        db.expire(item)
        raise _reject_from_db(error) from error
    await _journal(db, item, on, before, editor)
    return item


def _journalled(item: PlanItem) -> dict[str, str | None]:
    """
    Значения полей, за которыми следит журнал правок (`#150`).

    Ровно те, по которым видно, что человек переставил: два конца окна, текст,
    место в плане. Снимаются до правки и сравниваются после — правка, ничего не
    изменившая, строки не пишет.
    """
    return {
        FIELD_WINDOW_START: _clock(item.starts_at),
        FIELD_WINDOW_END: _clock(item.ends_at),
        FIELD_TEXT: item.text_md,
        FIELD_ORD: str(item.ord),
        FIELD_SECTION_ID: str(item.section_id),
    }


def _clock(value: datetime | None) -> str | None:
    """
    Момент окна как «ЧЧ:ММ» на часах человека.

    Через `local_time`, а не `strftime` по хранимому UTC: диф читает человек, и
    «было 07:00, стало 12:00» про девять утра — не то, что он делал.
    """
    return None if value is None else local_time(value).strftime("%H:%M")


async def clear_needs_review(db: AsyncSession, on: date) -> None:
    """
    Снять пометку «собран ночью, не проверен» с плана этой даты.

    Зовётся из путей правки пункта и из первой отметки дня (`#151`). Отдельной
    ручки «я посмотрел» нет намеренно: пометка снимается действием с планом, а
    кнопка подтверждения — это ещё одно место, где можно соврать себе.
    """
    plan = await get_plan(db, on)
    if plan is not None and plan.needs_review:
        plan.needs_review = False
        await db.flush()


async def _journal(
    db: AsyncSession,
    item: PlanItem,
    on: date,
    before: dict[str, str | None],
    editor: str,
) -> None:
    """
    Записать в журнал всё, что эта правка изменила.

    Правки, сделанные генерацией, в журнал не идут: автором правки человека
    помечается только человек, иначе диф «что человек переставил» посчитает
    саму же машину.
    """
    if editor != EDITED_BY_HUMAN:
        return
    await clear_needs_review(db, on)
    after = _journalled(item)
    for name, old_value in before.items():
        await revision_crud.record_change(
            db, item, on, name, old_value, after[name], AUTHOR_HUMAN
        )


async def add_item(
    db: AsyncSession,
    on: date,
    section_id: uuid.UUID,
    payload: PlanItemCreate,
    editor: str = EDITED_BY_HUMAN,
    boundary: DayBoundary | None = None,
) -> PlanItem:
    """
    Новый пункт в конец своего уровня секции.

    `PlanSectionNotFound` — секции нет в плане этого дня; родитель из другой
    секции — тот же отказ, потому что уровень определяется парой «секция плюс
    родитель», и половина пары из чужого плана уровнем не является.
    """
    section = await _section_of_day(db, on, section_id)
    if section is None:
        raise PlanSectionNotFound(section_id)
    if payload.parent_id is not None:
        parent = await _item_of_day(db, on, payload.parent_id)
        if parent is None or parent.section_id != section_id:
            raise PlanItemNotFound(payload.parent_id)

    siblings = await _level(db, section_id, payload.parent_id)
    item = PlanItem(
        id=uuid.uuid4(),
        section_id=section_id,
        parent_id=payload.parent_id,
        ord=len(siblings),
        kind=payload.kind,
        rigidity=payload.rigidity,
        text_md=payload.text_md,
        text_plain=to_plain(payload.text_md),
        window_comment=payload.window_comment,
        code=payload.code,
        done_criterion=payload.done_criterion,
        why_md=payload.why_md,
        plan_md=payload.plan_md,
        external_ref=payload.external_ref,
        extra=dict(payload.extra),
        quarter_goal_id=payload.quarter_goal_id,
        unlinked_reason=payload.unlinked_reason,
        quick_mark_id=payload.quick_mark_id,
        carry_count=0,
        edited_by=editor,
        updated_at=datetime.now(timezone.utc),
    )
    _apply_window(
        item,
        payload.window,
        on,
        boundary if boundary is not None else current_boundary(),
    )
    # Проверка до `db.add`: пункт, который правила не пропускают, в сессию не
    # попадает вовсе, и убирать его оттуда потом не приходится.
    await _check_row_rules(db, item)
    db.add(item)
    try:
        await db.flush()
    except IntegrityError as error:
        db.expunge(item)
        raise _reject_from_db(error) from error
    if editor == EDITED_BY_HUMAN:
        # Появление строки — тоже правка, и без неё пункт, которого машина не
        # предлагала, читался бы на экране как непонятый: изменён, а записи нет.
        await revision_crud.record_change(
            db, item, on, FIELD_STATUS, None, "added", AUTHOR_HUMAN
        )
        await clear_needs_review(db, on)
    return item


async def remove_item(db: AsyncSession, on: date, item_id: uuid.UUID) -> None:
    """
    Удалить пункт вместе с его детьми и сомкнуть уровень.

    Дети уезжают каскадом внешнего ключа: «Минимум» тренировки без своей задачи
    — сирота, которую 29 августа уже показало как пункт, никем не сделанный.
    """
    item = await _item_of_day(db, on, item_id)
    if item is None:
        raise PlanItemNotFound(item_id)
    section_id, parent_id = item.section_id, item.parent_id
    await db.delete(item)
    await db.flush()
    await _renumber(db, section_id, parent_id)
    await clear_needs_review(db, on)


async def move_item(
    db: AsyncSession, on: date, item_id: uuid.UUID, move: PlanItemMove
) -> PlanItem:
    """
    Перенести пункт на место `position` уровня `(section_id, parent_id)`.

    Оба уровня — исходный и приёмный — перенумеровываются одной транзакцией.
    Позиция больше длины уровня означает «в конец», а не отказ: перетаскивание
    в пустоту под последним пунктом — это «в конец», и отвечать на него 422
    значит спорить с рукой.
    """
    item = await _item_of_day(db, on, item_id)
    if item is None:
        raise PlanItemNotFound(item_id)
    section = await _section_of_day(db, on, move.section_id)
    if section is None:
        raise PlanSectionNotFound(move.section_id)
    if move.parent_id is not None:
        parent = await _item_of_day(db, on, move.parent_id)
        if parent is None or parent.section_id != move.section_id:
            raise PlanItemNotFound(move.parent_id)
        if move.parent_id == item.id:
            raise PlanRejected(
                error="item_cannot_parent_itself",
                message="Пункт не может стать своим же родителем.",
            )

    before = _journalled(item)
    source_section, source_parent = item.section_id, item.parent_id
    same_level = source_section == move.section_id and source_parent == move.parent_id

    target = [
        row
        for row in await _level(db, move.section_id, move.parent_id)
        if row.id != item.id
    ]
    target.insert(min(move.position, len(target)), item)

    item.section_id = move.section_id
    item.parent_id = move.parent_id
    item.edited_by = EDITED_BY_HUMAN
    item.updated_at = datetime.now(timezone.utc)

    # Перестановка не может нарушить ни одного `CHECK`: меняются только место и
    # родитель. Уникальность позиции отложена до коммита и потому переживает
    # промежуточное состояние, в котором два пункта на миг делят один `ord`.
    await _renumber(db, move.section_id, move.parent_id, target)
    if not same_level:
        await _renumber(db, source_section, source_parent)
    await _journal(db, item, on, before, EDITED_BY_HUMAN)
    return item


def _facts_of(item: PlanItem) -> ItemFacts:
    """Один хранимый пункт как факты, которые умеет судить `plan_validate`."""
    return ItemFacts(
        kind=item.kind,
        rigidity=item.rigidity,
        code=item.code,
        text_plain=item.text_plain,
        has_window=item.starts_at is not None and item.ends_at is not None,
        has_criterion=bool(item.done_criterion),
        is_goal_linked=(item.quarter_goal_id is not None or bool(item.unlinked_reason)),
        quarter_goal_id=item.quarter_goal_id,
    )


async def _check_row_rules(db: AsyncSession, item: PlanItem) -> None:
    """
    Правила строки — до записи, чтобы отказ назвал пункт, а не ограничение.

    Дублирование с `CHECK` одностороннее и намеренное, как в `plan_validate`:
    база делает правило истинным для всех писателей, а это — ответ, в котором
    есть код пункта. Проверка до `flush` нужна ещё и затем, чтобы отвергнутая
    правка не оставила в сессии грязный объект: `IntegrityError` в разгар
    записи чинится откатом, а откат уносит и всё, что транзакция уже сделала.
    """
    facts = _facts_of(item)
    check_item_shape([facts])
    named = {facts.quarter_goal_id} if facts.quarter_goal_id is not None else set()
    check_goal_exists([facts], await goal_crud.existing_goal_ids(db, named))


def _stored_facts(plan: DayPlan) -> list[ItemFacts]:
    """Хранимый план как факты, которые умеет судить `app.day.plan_validate`."""
    return [
        ItemFacts(
            kind=item.kind,
            rigidity=item.rigidity,
            code=item.code,
            text_plain=item.text_plain,
            has_window=item.starts_at is not None and item.ends_at is not None,
            has_criterion=bool(item.done_criterion),
            is_goal_linked=(
                item.quarter_goal_id is not None or bool(item.unlinked_reason)
            ),
            quarter_goal_id=item.quarter_goal_id,
        )
        for section in plan.sections
        for item in section.items
    ]


async def human_warnings(
    db: AsyncSession, plan: DayPlan, rule: DayRuleSet
) -> list[PlanRejected]:
    """
    Правила документа, которые правка человека нарушила, но которые её не рвут.

    Асимметрия строгости: машине нарушение блокирует запись (`replace_plan`
    поднимает `PlanRejected` до единой строки), человеку — нет. Здесь те же
    правила прогоняются по уже сохранённому плану и возвращаются списком.

    Проверки зовутся по одной, а не через `validate_plan`: он поднимает первое
    же нарушение, и человек чинил бы их по одному за запрос.
    """
    facts = _stored_facts(plan)
    named = {fact.quarter_goal_id for fact in facts if fact.quarter_goal_id is not None}
    if plan.quarter_goal_id is not None:
        named.add(plan.quarter_goal_id)
    known = await goal_crud.existing_goal_ids(db, named)
    warnings: list[PlanRejected] = []
    try:
        check_goal_exists(facts, known, plan.quarter_goal_id)
    except PlanRejected as broken:
        warnings.append(broken)
    try:
        check_hard_rigidity(facts, rule)
    except PlanRejected as broken:
        warnings.append(broken)
    try:
        check_task_bar(facts, rule)
    except PlanRejected as broken:
        warnings.append(broken)
    return warnings


__all__ = [
    "clear_needs_review",
    "PlanItemNotFound",
    "PlanRejected",
    "PlanSectionNotFound",
    "add_item",
    "build_schedule",
    "delete_plan",
    "draft_of",
    "edit_item",
    "find_overlaps",
    "get_plan",
    "human_warnings",
    "move_item",
    "prepare_plan",
    "remove_item",
    "replace_plan",
    "to_response",
]


def draft_of(
    document: PlanDocument,
    on: date,
    boundary: DayBoundary | None = None,
) -> PlanDraft:
    """
    The document as the draft `app.day.constraints` judges.

    A second reading of the same rows rather than a second source of truth:
    `prepare_plan` already resolved every window across midnight, and the draft
    is those resolved rows with the text dropped. Dropping it is the point — a
    violation outlives the plan, and nothing downstream may be able to quote a
    line.

    Section kinds travel with the items so `task_cap` can count what is study
    and what is work without asking which section a row came from twice.
    """
    resolved_boundary = boundary if boundary is not None else current_boundary()
    _, flat = prepare_plan(document, on, resolved_boundary)
    section_kinds = [section.kind for section in document.sections]
    return PlanDraft(
        target=on,
        items=tuple(
            DraftItem(
                item_id=row.id,
                kind=row.source.kind,
                rigidity=row.source.rigidity,
                code=row.source.code,
                section_kind=(
                    section_kinds[row.section_index]
                    if row.section_index < len(section_kinds)
                    else ""
                ),
                day_date=on,
                starts_at=row.starts_at,
                ends_at=row.ends_at,
            )
            for row in flat
        ),
    )
