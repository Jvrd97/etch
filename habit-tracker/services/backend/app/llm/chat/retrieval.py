# [review:need-review] PHASE-03/114, PHASE-03/190
# summary: PHASE-03/190 checks `state` of inbox_tasks against SIGNAL_STATES, so a name outside the dictionary is a refusal the model can act on instead of an empty result it reports as "there is nothing there"
# summary: the white list of six named retrievals the chat may ask for by name — a Pydantic params schema with a ceiling per name, execution through the existing CRUD and nothing of its own, a refusal that never reaches the database for a seventh name, and an outcome row per call (including the refused ones) that `chat_retrievals` is written from
"""
Именованные выборки чата: белый список, потолки, отказы.

**Список — граница, а не подсказка.** Имён ровно шесть, и седьмое стоит правки
этого файла. Имя вне списка не доходит до базы: `run_need` возвращает отказ
текстом, модель переспрашивает или обходится карточкой дня. Ни одной ветки, где
незнакомое имя превращается в запрос, здесь нет — именно поэтому реестр отделён
от исполнения, а не собирается из `getattr`.

**Параметры валидируются схемой на каждое имя, и у каждой схемы есть потолок.**
Без потолка «выборка по имени» превращается в «SELECT всего» через параметры:
диапазон в три года и `table_slice` на сто тысяч строк — это те же данные, что и
без белого списка, только через дверь. Потолок диапазона — квартал, потолок
строк — `MAX_ROWS`.

**Своего SQL здесь нет.** Каждая выборка идёт существующим CRUD, тем же, что
отдаёт эти числа экрану. Второй путь к данным означал бы, что «сколько я прошёл»
имеет два ответа, и разошлись бы они молча — ровно та причина, по которой
карточка дня берёт дневные свёртки у `health.daily_values`, а не считает свои.

**Отказ — тоже выборка.** Строка в `chat_retrievals` пишется и на отвергнутое
имя, и на отвергнутые параметры, с `row_count = 0`. Журнал отвечает на вопрос
«какие данные уходили», и попытка, не дошедшая до базы, — часть этого ответа.

**Потолок заходов за ход конечный.** Модель, зациклившаяся на `need`, обязана
остановиться и ответить словами: круг без потолка — это ожидание человека до
срока хода, то есть худший из отказов.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date as date_type
from typing import Any, Generic, Protocol, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import entry as entry_crud
from app.crud import health as health_crud
from app.crud import inbox as inbox_crud
from app.crud import journal as journal_crud
from app.models.inbox import SIGNAL_STATE_NEW, SIGNAL_STATES
from app.crud import streak as streak_crud
from app.crud import table as table_crud
from app.llm.chat.context import build_day_card
from app.llm.plan_flow import extract_json

# Шесть имён и седьмого нет. Строки, а не enum: они уезжают в промпт текстом и
# приезжают из ответа модели текстом, и превращать их в тип по дороге незачем.
QUERY_DAY_CARD = "day_card"
QUERY_ENTRIES_RANGE = "entries_range"
QUERY_JOURNAL_RANGE = "journal_range"
QUERY_HEALTH_DAILY = "health_daily"
QUERY_STREAK = "streak"
QUERY_TABLE_SLICE = "table_slice"
# Задачи, приехавшие снаружи через контур входящих (`#97`). Единственный путь,
# которым ClickUp попадает в разговор: CLI запускается с `--tools ""` и наружу
# не ходит вовсе, поэтому «модель сходит и посмотрит» — не вариант ни в каком
# виде. Читается таблица `inbound_signals`, наполняет её опрос источника.
QUERY_INBOX_TASKS = "inbox_tasks"

# Потолок диапазона — квартал. Не «год, чтобы точно хватило»: сравнение недели с
# позапрошлой укладывается в две недели, а год строк — это уже не выборка, а
# выгрузка базы через белый список.
MAX_RANGE_DAYS = 92

# Потолок числа строк одной выборки. Тот же порядок, что у диапазона: столько
# строк человек ещё может прочитать в ответе, а модель — удержать в контексте.
MAX_ROWS = 500

# Сколько имён модель может попросить одним блоком. Шесть — весь список разом,
# и просить больше нечего.
MAX_NEED_ITEMS = 6

# Сколько раз за один ход модель может уйти за данными. Два: первый заход —
# нормальный «мне не хватило карточки», второй — «в первом я ошибся именем».
# Третий — это цикл, и он оплачивается ожиданием человека.
MAX_NEED_PASSES = 2

# Маркер, по которому ответ признаётся запросом данных. Не «есть фигурная
# скобка»: модель цитирует JSON в объяснениях.
NEED_MARKER = '"need"'

# Коды отказа. Машинные: они ложатся в `chat_retrievals.query_name`-соседство
# как часть параметров и читаются на экране расшифровкой, а не как есть.
REFUSAL_UNKNOWN_QUERY = "unknown_query"
REFUSAL_BAD_PARAMS = "bad_params"
REFUSAL_TOO_MANY = "too_many_queries"


@dataclass(frozen=True)
class NeedItem:
    """Одна просьба модели: имя выборки и параметры, как она их назвала."""

    query: str
    params: dict[str, Any]


@dataclass(frozen=True)
class QueryRows:
    """Что вернула выборка: строки для модели и сколько их было в базе."""

    lines: list[str]
    row_count: int


@dataclass(frozen=True)
class RetrievalOutcome:
    """
    Итог одной выборки — и исполненной, и отвергнутой.

    `refusal` заполнен ровно тогда, когда до базы дело не дошло. Отвергнутая
    выборка не «ничего не произошло»: у неё `row_count = 0`, своя строка в
    журнале и свой текст для модели, объясняющий, почему данных не будет.
    """

    query_name: str
    params: dict[str, Any]
    text: str
    row_count: int
    refusal: str | None = None

    @property
    def chars(self) -> int:
        """Сколько знаков данных ушло модели по этой выборке."""
        return len(self.text)


class DayCardParams(BaseModel):
    """Карточка одного дня — того же вида, что уходит в промпт."""

    model_config = ConfigDict(extra="forbid")

    date: date_type


class RangeParams(BaseModel):
    """
    Диапазон дат с потолком.

    Потолок стоит здесь, а не в исполнителе, по той же причине, по которой
    `minutes > 0` стоит в таблице, а не в сервисе: проверку обязаны пройти все
    четыре выборки, а исполнителей у них четыре разных.
    """

    model_config = ConfigDict(extra="forbid")

    date_from: date_type
    date_to: date_type

    @model_validator(mode="after")
    def _within_ceiling(self) -> RangeParams:
        if self.date_to < self.date_from:
            raise ValueError("date_to is earlier than date_from")
        span = (self.date_to - self.date_from).days + 1
        if span > MAX_RANGE_DAYS:
            raise ValueError(f"range of {span} days is over the {MAX_RANGE_DAYS} cap")
        return self


class RowsRangeParams(RangeParams):
    """Диапазон плюс явный потолок строк — для выборок, длина которых не от дней."""

    limit: int = Field(default=100, ge=1, le=MAX_ROWS)


class InboxTasksParams(BaseModel):
    """
    Что взять из входящих.

    Умолчания названы так, чтобы обычный вопрос «что у меня по задачам» не
    требовал параметров вовсе: неразобранное, тридцать строк. Разобранное и
    отклонённое модель просит явно — иначе в контекст поедет архив.

    **Состояние проверяется по словарю, а не подставляется в запрос как есть.**
    Строка вне словаря давала бы `WHERE state = <мимо>` — ноль строк без единого
    признака, что спросили не то. Наблюдалось 01.09.2026: модель попросила
    `state: "all"`, получила пустую выборку и сказала человеку, что во входящих
    ничего нет — уверенно и неправдиво. Ноль строк и «такого состояния нет» —
    разные ответы, и отказ здесь и есть способ их различить.

    `None` — «все состояния», и это единственный способ так сказать; он назван
    в подсказке рядом со словарём.
    """

    model_config = ConfigDict(extra="forbid")

    state: str | None = Field(default=SIGNAL_STATE_NEW)
    limit: int = Field(default=30, ge=1, le=MAX_ROWS)

    @field_validator("state")
    @classmethod
    def _known_state(cls, value: str | None) -> str | None:
        """
        Состояние из словаря модели входящих — или отказ.

        Словарь берётся из `SIGNAL_STATES`, а не переписывается здесь списком:
        второй список разошёлся бы с первым на первой же правке, и разошёлся бы
        молча — именно молчание и чинит этот валидатор.
        """
        if value is not None and value not in SIGNAL_STATES:
            raise ValueError(
                f"unknown signal state {value!r}; known: {', '.join(SIGNAL_STATES)}"
            )
        return value


class StreakParams(BaseModel):
    """Серия одной категории."""

    model_config = ConfigDict(extra="forbid")

    category_id: int = Field(ge=1)


def _fmt_date(value: date_type) -> str:
    """Дата в ответе модели — ISO, тем же видом, что и везде в контракте."""
    return value.isoformat()


async def _run_day_card(db: AsyncSession, params: DayCardParams) -> QueryRows:
    """Карточка дня — та же `build_day_card`, что склеивается в системный промпт."""
    card = await build_day_card(db, params.date)
    lines = card.text.splitlines()
    return QueryRows(lines=lines, row_count=len(lines))


async def _run_entries_range(db: AsyncSession, params: RowsRangeParams) -> QueryRows:
    """Записи трекера за диапазон, по строке на запись."""
    entries = await entry_crud.get_entries(
        db,
        limit=params.limit,
        start_date=params.date_from,
        end_date=params.date_to,
    )
    lines = [
        f"{_fmt_date(one.entry_date)} категория {one.category_id}: "
        + ", ".join(f"поле {value.field_id} = {value.value}" for value in one.values)
        for one in entries
    ]
    return QueryRows(lines=lines, row_count=len(entries))


async def _run_journal_range(db: AsyncSession, params: RowsRangeParams) -> QueryRows:
    """Тексты дневника за диапазон. Заголовок и настроение — строкой над текстом."""
    entries, _total = await journal_crud.get_journal_entries(
        db,
        limit=params.limit,
        start_date=params.date_from,
        end_date=params.date_to,
    )
    lines: list[str] = []
    for one in entries:
        header = one.title or "без заголовка"
        lines.append(f"{_fmt_date(one.entry_date)} — {header}:")
        if one.mood:
            lines.append(f"  настроение: {one.mood}")
        lines.extend(f"  {line}" for line in one.content.splitlines())
    return QueryRows(lines=lines, row_count=len(entries))


async def _run_health_daily(db: AsyncSession, params: RangeParams) -> QueryRows:
    """
    Дневные свёртки здоровья — ровно те числа, что отдаёт `GET /health/metrics`.

    Свёртка идёт тем же `daily_values`, что и ручка: сравнение сна за две недели
    обязано сойтись с экраном до знака, а два пути к одному числу расходятся.
    """
    metrics = await health_crud.get_catalog(db)
    if not metrics:
        return QueryRows(lines=[], row_count=0)
    days = await health_crud.daily_values(db, metrics, params.date_from, params.date_to)
    lines: list[str] = []
    rows = 0
    for metric in metrics:
        for day_value in days.get(metric.id, []):
            rows += 1
            lines.append(
                f"{_fmt_date(day_value.local_date)} {metric.display_name}: "
                f"{day_value.value:g} {metric.canonical_unit}"
            )
    return QueryRows(lines=lines, row_count=rows)


async def _run_streak(db: AsyncSession, params: StreakParams) -> QueryRows:
    """Серия одной категории — тем же расчётом, что и на экране."""
    stats = await streak_crud.get_category_streak(db, params.category_id)
    last = (
        _fmt_date(stats.last_relapse_date)
        if stats.last_relapse_date is not None
        else "срывов не было"
    )
    return QueryRows(
        lines=[
            f"категория {params.category_id}: текущая серия {stats.current_streak}, "
            f"лучшая {stats.best_streak}, последний срыв: {last}"
        ],
        row_count=1,
    )


async def _run_table_slice(db: AsyncSession, params: RowsRangeParams) -> QueryRows:
    """
    Свод таблицы за диапазон — те же свёртки по полям, что рисует экран таблицы.

    Потолок строк режет именно ячейки, а не дни: диапазон уже ограничен своей
    схемой, а число ячеек в дне зависит от того, сколько категорий человек завёл.
    """
    table = await table_crud.get_table(
        db, date_from=params.date_from, date_to=params.date_to
    )
    lines: list[str] = []
    rows = 0
    for day in table.days:
        for cell in day.cells:
            rows += 1
            if len(lines) < params.limit:
                lines.append(
                    f"{_fmt_date(day.date)} категория {cell.category_id} "
                    f"поле {cell.field_id}: {cell.aggregated_value}"
                )
    return QueryRows(lines=lines, row_count=rows)


async def _run_inbox_tasks(db: AsyncSession, params: InboxTasksParams) -> QueryRows:
    """
    Задачи и письма, приехавшие снаружи, — заголовок и ссылка обратно.

    Тела здесь нет и взяться ему неоткуда: контур его не хранит (ADR-0016, D2).
    Модель получает то же, что человек видит на экране «Входящие», — и ссылку,
    по которой человек вернётся к оригиналу.
    """
    rows = await inbox_crud.list_signals(db, state=params.state, limit=params.limit)
    lines = [
        f"{_fmt_date(row.local_date)} {row.external_id}: "
        f"{row.title or '(без заголовка)'}"
        + (f" — {row.external_url}" if row.external_url else "")
        for row in rows
    ]
    return QueryRows(lines=lines, row_count=len(rows))


ParamsT = TypeVar("ParamsT", bound=BaseModel)


class NamedQuery(Protocol):
    """
    Одно имя белого списка: провалидировать параметры и исполнить.

    Протокол, а не базовый класс: реестр обязан быть однородным словарём, а
    схемы параметров у выборок разные, и обобщённый конкретный тип под этим
    протоколом даёт mypy проверить каждую пару «схема — исполнитель».
    """

    async def execute(self, db: AsyncSession, params: dict[str, Any]) -> QueryRows: ...


@dataclass(frozen=True)
class _Named(Generic[ParamsT]):
    """Пара «схема параметров — исполнитель», связанная одним типом."""

    params_model: type[ParamsT]
    run: Callable[[AsyncSession, ParamsT], Awaitable[QueryRows]]

    async def execute(self, db: AsyncSession, params: dict[str, Any]) -> QueryRows:
        return await self.run(db, self.params_model.model_validate(params))


# Белый список. Правка этого словаря — единственный способ появиться седьмому
# имени, и она видна в диффе.
NAMED_QUERIES: dict[str, NamedQuery] = {
    QUERY_DAY_CARD: _Named(DayCardParams, _run_day_card),
    QUERY_ENTRIES_RANGE: _Named(RowsRangeParams, _run_entries_range),
    QUERY_JOURNAL_RANGE: _Named(RowsRangeParams, _run_journal_range),
    QUERY_HEALTH_DAILY: _Named(RangeParams, _run_health_daily),
    QUERY_STREAK: _Named(StreakParams, _run_streak),
    QUERY_TABLE_SLICE: _Named(RowsRangeParams, _run_table_slice),
    QUERY_INBOX_TASKS: _Named(InboxTasksParams, _run_inbox_tasks),
}


# Как каждое имя описано модели. Отдельно от реестра, но проверяется тестом на
# совпадение ключей: описание, отставшее от схемы, — это модель, зовущая выборку
# несуществующим параметром на каждом ходу.
QUERY_HINTS: dict[str, str] = {
    QUERY_DAY_CARD: "карточка одного дня целиком — `date`",
    QUERY_ENTRIES_RANGE: (
        "записи трекера за диапазон — `date_from`, `date_to`, `limit`"
    ),
    QUERY_JOURNAL_RANGE: (
        "тексты дневника за диапазон — `date_from`, `date_to`, `limit`"
    ),
    QUERY_HEALTH_DAILY: (
        "дневные числа здоровья (сон, шаги, пульс) — `date_from`, `date_to`"
    ),
    QUERY_STREAK: "серия по категории — `category_id`",
    QUERY_TABLE_SLICE: (
        "свод таблицы по полям за диапазон — `date_from`, `date_to`, `limit`"
    ),
    QUERY_INBOX_TASKS: (
        "задачи и письма, приехавшие снаружи (ClickUp и прочие источники), "
        "с ссылкой обратно — `state` (`new` по умолчанию, ещё `parsed`, "
        "`ignored`, `duplicate`; `null` — все сразу, другого способа нет), "
        "`limit`"
    ),
}


def describe_queries() -> str:
    """Белый список строками для системного промпта — из реестра, а не рядом с ним."""
    return "\n".join(f"- `{name}` — {QUERY_HINTS[name]}" for name in NAMED_QUERIES)


def carries_need(text: str) -> bool:
    """Похоже ли, что ответ просит данные, а не отвечает человеку."""
    return NEED_MARKER in text


def parse_need(text: str) -> list[NeedItem] | None:
    """
    Просьбы о данных из ответа модели, либо `None`.

    Возвращает `None` на всём, что не является разборным блоком `need`: ответ
    без блока, битый JSON, `need` не списком. Разбор не бросает наружу по той же
    причине, что и разбор плана, — ход уже идёт, и отказ парсера означает
    «данных не просили», а не ошибку разговора.

    Элементы сверх `MAX_NEED_ITEMS` отбрасываются здесь, а не в исполнителе:
    отказ по числу имён не должен стоить шести обращений в базу.
    """
    if not carries_need(text):
        return None
    try:
        payload = json.loads(extract_json(text))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    raw = payload.get("need")
    if not isinstance(raw, list) or not raw:
        return None

    items: list[NeedItem] = []
    for one in raw[:MAX_NEED_ITEMS]:
        if not isinstance(one, dict):
            continue
        name = one.get("query")
        if not isinstance(name, str):
            continue
        params = one.get("params")
        items.append(
            NeedItem(query=name, params=params if isinstance(params, dict) else {})
        )
    return items or None


def _refusal(
    query: str, params: dict[str, Any], code: str, why: str
) -> RetrievalOutcome:
    """Отказ как выборка: свой текст модели, нулевой счётчик, своя строка журнала."""
    return RetrievalOutcome(
        query_name=query, params=params, text=why, row_count=0, refusal=code
    )


def _reason(error: ValidationError) -> str:
    """
    Причина отказа по параметрам — без значений, которые их вызвали.

    В логи и в ответ идут поле и тип ошибки. Само значение приехало от модели,
    но добраться до него оно могло только из реплики человека, а тексту реплики
    в служебных строках делать нечего.
    """
    return "; ".join(
        f"{'.'.join(str(part) for part in one['loc']) or 'params'}: {one['type']}"
        for one in error.errors()
    )


async def run_need(db: AsyncSession, items: list[NeedItem]) -> list[RetrievalOutcome]:
    """
    Исполнить просьбы модели, отказав всему, чего нет в списке.

    Порядок ответов — порядок просьб: модель сопоставляет их по имени, а
    перестановка сделала бы два запроса одного имени с разными параметрами
    неразличимыми.
    """
    outcomes: list[RetrievalOutcome] = []
    for item in items[:MAX_NEED_ITEMS]:
        query = NAMED_QUERIES.get(item.query)
        if query is None:
            outcomes.append(
                _refusal(
                    item.query,
                    item.params,
                    REFUSAL_UNKNOWN_QUERY,
                    "имя не входит в белый список; доступны: "
                    + ", ".join(sorted(NAMED_QUERIES)),
                )
            )
            continue
        try:
            rows = await query.execute(db, item.params)
        except ValidationError as exc:
            outcomes.append(
                _refusal(
                    item.query,
                    item.params,
                    REFUSAL_BAD_PARAMS,
                    f"параметры не прошли схему: {_reason(exc)}",
                )
            )
            continue
        outcomes.append(
            RetrievalOutcome(
                query_name=item.query,
                params=item.params,
                text="\n".join(rows.lines),
                row_count=rows.row_count,
            )
        )
    return outcomes


# Заголовок ответа сервера на блок `need`. Модель по нему отличает данные,
# которые ей выдали, от собственной прошлой реплики.
ANSWER_TITLE = "# Ответ на запрос данных"

# Что дописывается, когда заходы кончились. Формулировка несущая: это и есть
# инструкция «отвечай тем, что есть», а не пометка.
EXHAUSTED_LINE = (
    "Заходы за данными на этот ход кончились. Ответь человеку словами тем, "
    "что уже есть, и больше не проси данных."
)


def render_outcomes(outcomes: list[RetrievalOutcome], *, exhausted: bool) -> str:
    """
    Выборки текстом для следующего захода той же сессии.

    Пустая выборка подписана словами, а не пустотой под заголовком: «за эти дни
    ничего не записано» и «я не смог достать» — разные ответы, и второй модель
    обязана прочитать, иначе она допишет за него нули.
    """
    blocks: list[str] = [ANSWER_TITLE]
    for one in outcomes:
        params = json.dumps(one.params, ensure_ascii=False, sort_keys=True)
        blocks.append(f"## {one.query_name} {params}")
        if one.refusal is not None:
            blocks.append(f"отказ ({one.refusal}): {one.text}")
            continue
        blocks.append(f"строк: {one.row_count}")
        blocks.append(one.text if one.text else "записей нет")
    if exhausted:
        blocks.append(EXHAUSTED_LINE)
    return "\n\n".join(blocks)


__all__ = [
    "ANSWER_TITLE",
    "QUERY_HINTS",
    "describe_queries",
    "MAX_NEED_ITEMS",
    "MAX_NEED_PASSES",
    "MAX_RANGE_DAYS",
    "MAX_ROWS",
    "NAMED_QUERIES",
    "REFUSAL_BAD_PARAMS",
    "REFUSAL_TOO_MANY",
    "REFUSAL_UNKNOWN_QUERY",
    "NeedItem",
    "QueryRows",
    "RetrievalOutcome",
    "carries_need",
    "parse_need",
    "render_outcomes",
    "run_need",
]
