# [review:need-review] PHASE-03/139
# summary: the dry run of one rule over history without a single write, and the re-markup of a period that recomputes only what an importer wrote and never what a person confirmed, with a before/after of the shares
"""
Сухой прогон правила и переразметка периода.

**Прогон до сохранения — обязательная половина экрана, а не удобство.**
Правило `window_title_regex` без проверки на реальных данных ловит либо ничего,
либо всё. На приёме «сначала сохрани, потом посмотри» человек молча перестаёт
трогать правила — и таблица, заведённая ровно затем, чтобы меняться без деплоя,
меняется раз в квартал.

**Прогон не пишет ничего.** Ни строки, ни `flush`. Правило приезжает целиком в
теле запроса и живёт значением: `RuleCandidate` с `id = 0`, потому что у
неспасённого правила id ещё нет, а резолверу он нужен только для разрешения
ничьих по приоритету — и ноль там честнее выдуманного номера.

**Прогон отвечает не только «сколько», но и «у кого отобрал».** Совпадение,
которое новое правило забирает у существующего, — это и есть то, ради чего
человек смотрит на прогон: правило, ловящее сто интервалов, из которых
девяносто уже размечены верно, не улучшает разметку, а перекрашивает её.

**Переразметка не трогает `confirmed`.** То же правило B4, что у импортёров:
иначе первая же правка правил стирает всё, что человек поправил руками, и
доверие к ручному вводу кончается. Число защищённых строк едет наружу — молчание
здесь неотличимо от «их не было».

**Переразметка возвращает доли до и после.** Смысл операции — сдвинуть их;
операция, после которой надо идти на другой экран смотреть, что получилось, —
это операция, которую делают вслепую.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import role as role_crud
from app.models.role import RoleAct, RoleTimeBlock
from app.roles.matcher import RuleCandidate, resolve_rule
from app.roles.samples import KIND_ACT, HistoricalSample, historical_samples

# Сколько примеров совпадения показывается человеку. Пять: список, который
# читают глазами перед сохранением, а не выгрузка.
EXAMPLE_LIMIT = 5

# Id, под которым едет ещё не сохранённое правило. Ноль, а не выдуманный номер:
# резолверу он нужен только для разрешения ничьих, и ноль выигрывает ничью у
# любого сохранённого правила — новое правило равного веса человек пишет
# именно затем, чтобы оно применилось.
DRAFT_RULE_ID = 0


@dataclass(frozen=True)
class DryRunExample:
    """Одно совпадение, как его читает человек перед сохранением."""

    kind: str
    work_day: date
    label: str
    # Роль, к которой строка отнесена сейчас, и правило, которым она отнесена.
    # Пусто у строки, размеченной без правила — например, руками импортёра.
    current_role_id: int
    taken_from_rule_id: int | None


@dataclass(frozen=True)
class DryRun:
    """
    Итог прогона: сколько зацепило, у кого отобрало и на чём это считалось.

    `scanned_rows` едет рядом со счётчиками намеренно. Ноль совпадений на
    нулевой истории и ноль совпадений на месяце данных — разные ответы, и
    только второй читается как «правило не ловит».
    """

    date_from: date
    date_to: date
    scanned_rows: int
    matched_time_blocks: int
    matched_acts: int
    # Сколько совпадений отобрано у каждого существующего правила, по его id.
    taken_from: dict[int, int]
    # Сколько совпадений было ни за кем — чистое улучшение разметки.
    taken_from_nobody: int
    examples: list[DryRunExample]


@dataclass(frozen=True)
class RoleShare:
    """Доля одной роли в периоде — половина отчёта «до/после»."""

    role_id: int
    minutes: int
    share_pct: int


@dataclass(frozen=True)
class Reclassified:
    """
    Что переразметка сделала и чего не тронула.

    `protected` — строки, подтверждённые человеком. Их число называется вслух,
    потому что «ничего не изменилось» и «изменилось всё, кроме ваших правок» —
    разные исходы одной кнопки.
    """

    date_from: date
    date_to: date
    scanned_rows: int
    changed_time_blocks: int
    changed_acts: int
    protected: int
    before: list[RoleShare]
    after: list[RoleShare]


def _candidate(
    *, role_id: int, source: str, matcher_kind: str, pattern: str, priority: int
) -> RuleCandidate:
    """Ещё не сохранённое правило как значение для резолвера."""
    return RuleCandidate(
        id=DRAFT_RULE_ID,
        role_id=role_id,
        source=source,
        matcher_kind=matcher_kind,
        pattern=pattern,
        priority=priority,
    )


async def dry_run(
    db: AsyncSession,
    *,
    role_id: int,
    source: str,
    matcher_kind: str,
    pattern: str,
    priority: int,
    date_from: date,
    date_to: date,
) -> DryRun:
    """
    Прогнать правило по истории, не записав ни строки.

    Единственная база, к которой этот вызов обращается, — чтение: образцы
    периода и ничего больше. Отсутствие записи проверяется тестом, а не
    обещанием, и проверять его есть смысл именно здесь: это та половина экрана,
    без которой человек перестаёт трогать правила.
    """
    samples = await historical_samples(db, date_from, date_to)
    draft = _candidate(
        role_id=role_id,
        source=source,
        matcher_kind=matcher_kind,
        pattern=pattern,
        priority=priority,
    )

    matched_blocks = 0
    matched_acts = 0
    taken_from: dict[int, int] = {}
    taken_from_nobody = 0
    examples: list[DryRunExample] = []

    for one in samples:
        if resolve_rule(one.sample, [draft]) is None:
            continue
        if one.kind == KIND_ACT:
            matched_acts += 1
        else:
            matched_blocks += 1
        if one.rule_id is None:
            taken_from_nobody += 1
        else:
            taken_from[one.rule_id] = taken_from.get(one.rule_id, 0) + 1
        if len(examples) < EXAMPLE_LIMIT:
            examples.append(
                DryRunExample(
                    kind=one.kind,
                    work_day=one.work_day,
                    label=one.label,
                    current_role_id=one.role_id,
                    taken_from_rule_id=one.rule_id,
                )
            )

    return DryRun(
        date_from=date_from,
        date_to=date_to,
        scanned_rows=len(samples),
        matched_time_blocks=matched_blocks,
        matched_acts=matched_acts,
        taken_from=taken_from,
        taken_from_nobody=taken_from_nobody,
        examples=examples,
    )


def _shares(
    samples: list[HistoricalSample], minutes: dict[int, int]
) -> list[RoleShare]:
    """Доли ролей по минутам, которые несут строки периода."""
    total = sum(minutes.values())
    roles = sorted({one.role_id for one in samples} | set(minutes))
    return [
        RoleShare(
            role_id=role_id,
            minutes=minutes.get(role_id, 0),
            share_pct=(round(minutes.get(role_id, 0) * 100 / total) if total else 0),
        )
        for role_id in roles
    ]


async def reclassify(
    db: AsyncSession, *, date_from: date, date_to: date
) -> Reclassified:
    """
    Разметить период заново по действующим правилам.

    Пересчитываются только строки автоматических источников, и только те, что не
    подтверждены человеком. Правило, добавленное сегодня, начинает действовать
    на месяц, разложенный вчера, — без этого `unassigned` не опустится ниже
    порога и сработает названный в ADR сигнал «автоматика не работает», хотя не
    работает не автоматика, а невозможность её починить задним числом.

    Возвращает доли до и после, посчитанные по одним и тем же строкам: сравнение
    имеет смысл ровно тогда, когда знаменатель у обеих половин один.
    """
    samples = await historical_samples(db, date_from, date_to)
    fallback = await role_crud.fallback_role_id(db)

    before_minutes: dict[int, int] = {}
    after_minutes: dict[int, int] = {}
    changed_blocks = 0
    changed_acts = 0
    protected = 0

    for one in samples:
        minutes = 0
        if one.kind != KIND_ACT:
            block = await db.get(RoleTimeBlock, one.row_id)
            minutes = block.minutes if block is not None else 0
        before_minutes[one.role_id] = before_minutes.get(one.role_id, 0) + minutes

        if one.confirmed:
            protected += 1
            after_minutes[one.role_id] = after_minutes.get(one.role_id, 0) + minutes
            continue

        resolution = await role_crud.resolve_role(db, one.sample)
        role_id = resolution.role_id if resolution.matched else fallback
        after_minutes[role_id] = after_minutes.get(role_id, 0) + minutes

        if one.kind == KIND_ACT:
            act = await db.get(RoleAct, one.row_id)
            if act is not None and act.role_id != role_id:
                act.role_id = role_id
                changed_acts += 1
            continue

        block = await db.get(RoleTimeBlock, one.row_id)
        if block is not None and (
            block.role_id != role_id or block.rule_id != resolution.rule_id
        ):
            if block.role_id != role_id:
                changed_blocks += 1
            block.role_id = role_id
            block.rule_id = resolution.rule_id

    await db.flush()
    return Reclassified(
        date_from=date_from,
        date_to=date_to,
        scanned_rows=len(samples),
        changed_time_blocks=changed_blocks,
        changed_acts=changed_acts,
        protected=protected,
        before=_shares(samples, before_minutes),
        after=_shares(samples, after_minutes),
    )


__all__ = [
    "EXAMPLE_LIMIT",
    "DryRun",
    "DryRunExample",
    "Reclassified",
    "RoleShare",
    "dry_run",
    "reclassify",
]
