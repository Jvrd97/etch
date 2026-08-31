# [review:need-review] PHASE-03/113, PHASE-03/187
# summary: build_day_card — the bounded day card that goes into the chat system prompt: a registry of sections with priorities, an explicit "записей нет" instead of a silent gap, and a ceiling held by eating the tail of the least important section rather than by slicing the string
# summary: PHASE-03/187 prints the code, the rigidity and the done criterion of every plan line, without which a rewrite of the day cannot keep a single mark
"""
Карточка дня: всё, что чат знает о дне, и ничего сверх того.

**Список секций, а не одна функция с десятью запросами.** Часть источников
приезжает отдельными тикетами (задачи и входящие сигналы — `#97`, `#101`), и
добавление секции обязано стоить строку в `DAY_CARD_SECTIONS`, а не переписывание
`build_day_card`. Секция, чей источник ещё не приехал, в реестре просто
отсутствует. Её строитель возвращает `None`, а не пустой список: «источника нет»
и «за день ничего не записано» — разные ответы, и второй модель обязана прочитать
словами, иначе она допишет за него нули.

**Потолок съедает хвост наименее приоритетной секции.** Грубый срез строки
обрывает карточку на середине числа, и модель дочитывает «прошёл 84» вместо
«8421». Поэтому выбывают строки целиком, снизу вверх по приоритету, а секция,
потерявшая строки, говорит об этом сама — иначе обрезка неотличима от отсутствия
данных.

**Почасовых корзин здесь нет.** В карточку идёт дневная свёртка тем же путём,
которым её отдаёт `GET /health/metrics`, поэтому цифра в разговоре и цифра на
экране — одно число, а не два похожих.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.daytime import local_time
from app.crud import category as category_crud
from app.crud import day as day_crud
from app.crud import health as health_crud
from app.crud import journal as journal_crud
from app.crud import mark as mark_crud
from app.crud import plan as plan_crud
from app.crud import table as table_crud

# Заголовок карточки. Модель по нему отличает данные дня от инструкции над ними.
CARD_TITLE = "# Карточка дня"

# Что печатается в секции, за которой нет ни одной строки. Формулировка
# несущая: она и есть ответ на «что у меня сегодня» в пустой день.
NO_DATA_LINE = "записей нет"

# Что печатается в секции, потерявшей строки на потолке.
DROPPED_LINE = "… не поместилось строк: {count}"

# Разделитель секций в тексте карточки.
SECTION_SEPARATOR = "\n\n"

# Сколько знаков числа переживают форматирование. Десять, а не `:g` по
# умолчанию: шесть значащих превращают 1 234 567 шагов в «1.23457e+06».
NUMBER_PRECISION = 10


def _format_number(value: float) -> str:
    """Число дневной свёртки текстом, без экспоненты и без лишних нулей."""
    return f"{value:.{NUMBER_PRECISION}g}"


@dataclass(frozen=True)
class SectionSpec:
    """
    Одна секция карточки: как её зовут, как она подписана и когда выбывает.

    `priority` — порядок важности, меньше значит важнее. Секции выбывают на
    потолке в обратном порядке, поэтому число здесь — это решение «чем платим,
    когда день не влезает», а не украшение.
    """

    name: str
    title: str
    priority: int
    build: Callable[[AsyncSession, date], Awaitable[list[str] | None]]


@dataclass
class _Draft:
    """Секция в работе: строки, которые ещё в карточке, и счётчик выбывших."""

    spec: SectionSpec
    lines: list[str]
    dropped: int = 0


@dataclass(frozen=True)
class DayCard:
    """
    Готовая карточка: текст для промпта и всё, чем его характеризуют экрану.

    `dropped_sections` — имена секций, потерявших строки, в порядке выбывания.
    Без него пометка «обрезано» не отвечает на единственный вопрос, который её
    вызывает: чего именно модель не увидела.
    """

    entry_date: date
    text: str
    chars: int
    max_chars: int
    truncated: bool
    dropped_sections: tuple[str, ...] = field(default=())


async def _plan_section(db: AsyncSession, on: date) -> list[str] | None:
    """
    План дня строками, каждая со своей отметкой и запиской «как прошло».

    Код строки печатается рядом с её видом, и это не украшение: перезапись дня
    сохраняет отметку той строки, чей код вернулся в новом плане (`#187`). Не
    видя кодов, модель может только стереть прожитый день — предложить
    сохранение того, чего она не знает, нечем.

    Жёсткость и критерий готовности стоят там же и по той же причине: план,
    переписанный без них, теряет то, что канон с него спросит, и падает на
    проверке правил вместо того, чтобы доехать до человека.
    """
    plan = await plan_crud.get_plan(db, on)
    if plan is None:
        return []

    marks = {mark.item_id: mark for mark in await mark_crud.list_marks(db, on)}
    lines: list[str] = []
    if plan.title:
        lines.append(f"Заголовок: {plan.title}")
    for section in plan.sections:
        lines.append(f"— {section.title or section.kind} ({section.kind}):")
        for item in section.items:
            parts = [f"  · [{item.kind}/{item.rigidity}]"]
            if item.code:
                parts.append(f"код {item.code}")
            if item.starts_at is not None and item.ends_at is not None:
                start = local_time(item.starts_at).strftime("%H:%M")
                end = local_time(item.ends_at).strftime("%H:%M")
                parts.append(f"{start}–{end}")
            parts.append(item.text_plain)
            if item.done_criterion:
                parts.append(f"(сделано: {item.done_criterion})")
            mark = marks.get(item.id)
            parts.append(f"— отметка: {mark.state}" if mark else "— отметки нет")
            if mark is not None and mark.note:
                parts.append(f"(как прошло: {mark.note})")
            lines.append(" ".join(parts))
    return lines


async def _health_section(db: AsyncSession, on: date) -> list[str] | None:
    """
    Дневные свёртки здоровья — ровно те числа, что отдаёт `GET /health/metrics`.

    Свёртка берётся тем же `daily_values`, что и ручка: иначе «сколько я сегодня
    прошёл» имело бы два ответа, и разошлись бы они молча.
    """
    metrics = await health_crud.get_catalog(db)
    if not metrics:
        return []
    days = await health_crud.daily_values(db, metrics, on, on)
    lines: list[str] = []
    for metric in metrics:
        for day_value in days.get(metric.id, []):
            lines.append(
                f"{metric.display_name}: {_format_number(day_value.value)} "
                f"{metric.canonical_unit}"
            )
    return lines


async def _entries_section(db: AsyncSession, on: date) -> list[str] | None:
    """Записи трекера за день, свёрнутые по полю тем же путём, что и таблица."""
    categories = await category_crud.get_categories(db, limit=None, active_only=True)
    category_names = {one.id: one.name for one in categories}
    field_names = {
        one.id: one.name for category in categories for one in category.fields
    }

    table = await table_crud.get_table(db, date_from=on, date_to=on)
    lines: list[str] = []
    for day in table.days:
        for cell in day.cells:
            category = category_names.get(
                cell.category_id, f"категория {cell.category_id}"
            )
            name = field_names.get(cell.field_id, f"поле {cell.field_id}")
            lines.append(f"{category} / {name}: {cell.aggregated_value}")
    return lines


async def _journal_section(db: AsyncSession, on: date) -> list[str] | None:
    """
    Тексты дневника за день, включая блокнот дня.

    Блокнот отдельной секции не получает: `day.get_notebook` возвращает ту же
    строку `journal_entries`, и вторая секция была бы вторым показом одного
    текста.
    """
    entries = await journal_crud.get_journal_entries_by_date(db, on)
    lines: list[str] = []
    for entry in entries:
        header = entry.title or "без заголовка"
        lines.append(f"— {header}:")
        if entry.mood:
            lines.append(f"  настроение: {entry.mood}")
        if entry.tags:
            lines.append(f"  теги: {entry.tags}")
        lines.extend(f"  {line}" for line in entry.content.splitlines())
    return lines


# Реестр секций. Порядок в карточке — порядок этого списка; порядок выбывания на
# потолке — обратный порядку `priority`. Секции, чьих источников ещё нет
# (входящие сигналы `#101`, задачи `#97`), добавляются сюда строкой.
DAY_CARD_SECTIONS: tuple[SectionSpec, ...] = (
    SectionSpec("plan", "План дня и отметки", priority=10, build=_plan_section),
    SectionSpec("health", "Здоровье за день", priority=20, build=_health_section),
    SectionSpec("entries", "Записи трекера", priority=30, build=_entries_section),
    SectionSpec("journal", "Дневник", priority=40, build=_journal_section),
)


def _section_text(draft: _Draft) -> str:
    """Одна секция текстом: подпись, строки и честная пометка о потерях."""
    body = list(draft.lines)
    if draft.dropped:
        body.append(DROPPED_LINE.format(count=draft.dropped))
    elif not body:
        body.append(NO_DATA_LINE)
    return "\n".join([f"## {draft.spec.title}", *body])


def _render(header: Sequence[str], drafts: Sequence[_Draft]) -> str:
    """Карточка целиком: шапка и секции в порядке реестра."""
    return SECTION_SEPARATOR.join(
        ["\n".join(header), *(_section_text(draft) for draft in drafts)]
    )


async def _header(db: AsyncSession, on: date) -> list[str]:
    """
    Шапка карточки: дата и вид дня. Не выбывает никогда.

    Дата в карточке без шапки не существует — а без даты любое число в ней
    становится числом неизвестно когда.
    """
    lines = [f"{CARD_TITLE} — {on.isoformat()}"]
    day = await day_crud.get_day(db, on)
    if day is not None:
        nocode = "да" if day.is_nocode else "нет"
        lines.append(f"Вид дня: {day.kind}; no-code: {nocode}")
    return lines


async def build_day_card(
    db: AsyncSession,
    entry_date: date,
    *,
    max_chars: int | None = None,
    sections: Sequence[SectionSpec] | None = None,
) -> DayCard:
    """
    Карточка дня для системного промпта чата.

    Секции строятся по реестру, пустая секция говорит «записей нет», секция без
    источника отсутствует целиком. Итог укладывается в `max_chars`
    (по умолчанию `CHAT_CONTEXT_MAX_CHARS`): строки выбывают с хвоста наименее
    приоритетной секции, и только если после этого текст всё ещё длиннее
    потолка — срабатывает срез как последний рубеж.
    """
    ceiling = settings.CHAT_CONTEXT_MAX_CHARS if max_chars is None else max_chars
    specs = DAY_CARD_SECTIONS if sections is None else tuple(sections)

    header = await _header(db, entry_date)
    drafts: list[_Draft] = []
    for spec in specs:
        lines = await spec.build(db, entry_date)
        if lines is None:
            continue
        drafts.append(_Draft(spec=spec, lines=list(lines)))

    text = _render(header, drafts)
    dropped_order: list[str] = []
    if len(text) > ceiling:
        # Наименее приоритетная секция платит первой; внутри секции — хвост.
        for draft in sorted(drafts, key=lambda one: -one.spec.priority):
            if len(text) <= ceiling:
                break
            while len(text) > ceiling and draft.lines:
                draft.lines.pop()
                draft.dropped += 1
                text = _render(header, drafts)
            if draft.dropped:
                dropped_order.append(draft.spec.name)

    truncated = bool(dropped_order)
    if len(text) > ceiling:
        # Последний рубеж: потолок ниже, чем стоят одни только подписи секций.
        # Здесь срез неизбежен, и он честно объявлен обрезкой.
        text = text[:ceiling]
        truncated = True

    return DayCard(
        entry_date=entry_date,
        text=text,
        chars=len(text),
        max_chars=ceiling,
        truncated=truncated,
        dropped_sections=tuple(dropped_order),
    )
