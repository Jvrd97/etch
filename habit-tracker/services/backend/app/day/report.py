# [review:need-review] PHASE-03/145
# summary: сборка отчёта дня из одной только базы — отметки, заметки «как прошло», блокнот дня, тренировка и признак пропущенного ревью, каждый источник отчитывается о себе в `sources`, текст хэшируется, и пересборка на тех же данных возвращает ту же ревизию вместо новой
"""
Отчёт дня, собранный чтением базы и ничем больше.

**Ни подпроцессов, ни файлов.** Прежний `plans/**/<дата>.report.md` собирался из
четырёх источников сразу: отметки со страницы, блокнот дня, `git log` в
подпроцессе и файлы `notes/**`. Такой отчёт нельзя ни воспроизвести дважды
одинаково, ни покрыть тестом целиком. Здесь всё, что читается, — строки, и тест
гоняется на голой базе.

**Пустой источник объясняет себя.** Пока контур сигналов не подключён (`#146`),
коммитов в отчёте нет — и это написано словами в `sources`, а не оставлено
читателю на догадку «почему тут меньше, чем было».

**Пересборка на тех же данных не плодит ревизий.** `content_hash` — sha256 от
`content_md`; совпал с последней ревизией — возвращается она, и `built_at` не
сдвигается. Правка заметки «как прошло» меняет текст, а значит и хэш, а значит
появляется новая ревизия.

**В логах этого модуля нет ни текста пункта, ни заметки, ни отчёта.** Задача,
названная по диагнозу, — обычное дело, и отчёт целиком состоит из таких строк.
Здесь нет ни одного вызова логгера, и тест `test_day_report` это грепает.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import day as day_crud
from app.crud import mark as mark_crud
from app.crud import plan as plan_crud
from app.crud import training as training_crud
from app.models.day_report import TRIGGER_API, DayReport
from app.models.mark import PlanMark
from app.models.plan import DayPlan, PlanItem
from app.models.summary import SOURCE_CLOSE, STAGE_CLOSED, DaySummary

__all__ = [
    "SOURCE_KEYS",
    "SourceFact",
    "build_report",
    "latest_revision",
    "list_revisions",
    "read_revision",
    "render",
]

# Ключи `sources` — весь список источников отчёта, названный один раз. Экран
# рисует по нему строки «доступен / записей / почему пусто», и источник, забытый
# в сборке, виден как отсутствующий ключ, а не как молчание.
SOURCE_MARKS = "marks"
SOURCE_NOTES = "notes"
SOURCE_NOTEBOOK = "notebook"
SOURCE_TRAINING = "training"
SOURCE_SIGNALS = "signals"
SOURCE_KEYS: tuple[str, ...] = (
    SOURCE_MARKS,
    SOURCE_NOTES,
    SOURCE_NOTEBOOK,
    SOURCE_TRAINING,
    SOURCE_SIGNALS,
)

# Что говорит источник, которого в этом контуре ещё нет. Не пустая строка:
# «коммитов нет» и «коммиты никто не собирает» — разные факты, и отчёт беднее
# прежнего `.report.md` именно по второй причине.
SIGNALS_NOTE = "сигналов нет — контур не подключён (#146)"

# Заголовки разделов отчёта. Порядок фиксирован: отчёт — воспроизводимый текст,
# а не свободная вёрстка.
TITLE = "Отчёт дня"
MARKS_TITLE = "Отметки"
NOTES_TITLE = "Как прошло"
NOTEBOOK_TITLE = "Блокнот дня"
TRAINING_TITLE = "Тренировка"
SIGNALS_TITLE = "Сигналы"
CLOSING_TITLE = "Закрытие"

# Как отметка выглядит в тексте. Отсутствие строки `plan_mark` — `pending`, и
# это отдельное состояние, а не «не сделано».
STATE_MARK = {
    "done": "[x]",
    "failed": "[!]",
    "skipped": "[~]",
    "pending": "[ ]",
}
PENDING = "pending"

EMPTY_MARKS = "плана нет — отмечать было нечего"
EMPTY_MARKS_UNTOUCHED = "план есть, отметок нет"
EMPTY_NOTES = "заметок «как прошло» нет"
EMPTY_NOTEBOOK = "блокнот дня пуст"
EMPTY_TRAINING = "тренировки на этот день нет"
REVIEW_SKIPPED_NOTE = "ревью 15:40 не было — день закрыт одним касанием"


@dataclass(frozen=True)
class SourceFact:
    """
    Что один источник отдал отчёту.

    `note` пуст, когда источник отдал записи: объяснять нечего. Он обязателен
    ровно там, где записей нет, — иначе пустой раздел неотличим от сломанного.
    """

    available: bool
    count: int
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"available": self.available, "count": self.count, "note": self.note}


@dataclass(frozen=True)
class _Gathered:
    """Всё, что отчёт прочитал, до того как это стало текстом."""

    lines: list[str]
    sources: dict[str, SourceFact]


def _state_of(marks: dict[Any, PlanMark], item: PlanItem) -> str:
    mark = marks.get(item.id)
    return PENDING if mark is None else mark.state


def _label(item: PlanItem) -> str:
    """Пункт одной строкой: код, если он есть, и текст как он записан."""
    return f"{item.code} · {item.text_md}" if item.code else item.text_md


def _items_of(plan: DayPlan | None) -> list[PlanItem]:
    """Пункты плана в порядке разделов и позиций — тот же порядок на экране."""
    if plan is None:
        return []
    ordered: list[PlanItem] = []
    for section in sorted(plan.sections, key=lambda one: one.ord):
        ordered.extend(sorted(section.items, key=lambda one: one.ord))
    return ordered


async def _gather(db: AsyncSession, on: date) -> _Gathered:
    """Прочитать все источники и сложить строки отчёта в фиксированном порядке."""
    plan = await plan_crud.get_plan(db, on)
    marks = {mark.item_id: mark for mark in await mark_crud.list_marks(db, on)}
    items = _items_of(plan)

    lines: list[str] = [f"# {TITLE} {on.isoformat()}", ""]
    sources: dict[str, SourceFact] = {}

    lines.append(f"## {MARKS_TITLE}")
    lines.append("")
    if not items:
        lines.append(EMPTY_MARKS)
        sources[SOURCE_MARKS] = SourceFact(
            available=plan is not None, count=0, note=EMPTY_MARKS
        )
    else:
        for item in items:
            state = _state_of(marks, item)
            lines.append(f"- {STATE_MARK[state]} {_label(item)}")
        marked = sum(1 for item in items if item.id in marks)
        sources[SOURCE_MARKS] = SourceFact(
            available=True,
            count=marked,
            note="" if marked else EMPTY_MARKS_UNTOUCHED,
        )
    lines.append("")

    notes = [
        (item, marks[item.id].note)
        for item in items
        if item.id in marks and marks[item.id].note
    ]
    lines.append(f"## {NOTES_TITLE}")
    lines.append("")
    if not notes:
        lines.append(EMPTY_NOTES)
    for item, note in notes:
        lines.append(f"- {_label(item)}: {note}")
    lines.append("")
    sources[SOURCE_NOTES] = SourceFact(
        available=True, count=len(notes), note="" if notes else EMPTY_NOTES
    )

    notebook = await day_crud.get_notebook(db, on)
    text = "" if notebook is None else notebook.content.strip()
    lines.append(f"## {NOTEBOOK_TITLE}")
    lines.append("")
    lines.append(text if text else EMPTY_NOTEBOOK)
    lines.append("")
    sources[SOURCE_NOTEBOOK] = SourceFact(
        available=notebook is not None,
        count=1 if text else 0,
        note="" if text else EMPTY_NOTEBOOK,
    )

    training = await training_crud.get_training_day(db, on)
    lines.append(f"## {TRAINING_TITLE}")
    lines.append("")
    if training is None:
        lines.append(EMPTY_TRAINING)
    else:
        lines.append(f"- пропущена: {'да' if training.skipped else 'нет'}")
        lines.append(f"- паттерны: {', '.join(training.patterns) or 'нет'}")
        lines.append(f"- тяжёлые: {', '.join(training.heavy_patterns) or 'нет'}")
    lines.append("")
    sources[SOURCE_TRAINING] = SourceFact(
        available=training is not None,
        count=0 if training is None else 1,
        note="" if training is not None else EMPTY_TRAINING,
    )

    lines.append(f"## {SIGNALS_TITLE}")
    lines.append("")
    lines.append(SIGNALS_NOTE)
    lines.append("")
    sources[SOURCE_SIGNALS] = SourceFact(available=False, count=0, note=SIGNALS_NOTE)

    stored = await db.scalar(select(DaySummary).where(DaySummary.day_date == on))
    lines.append(f"## {CLOSING_TITLE}")
    lines.append("")
    if stored is None:
        lines.append("день не закрывали")
    else:
        lines.append(f"- стадия: {stored.stage}")
        if _review_skipped(stored):
            lines.append(f"- {REVIEW_SKIPPED_NOTE}")
    return _Gathered(lines=lines, sources=sources)


def _review_skipped(row: DaySummary) -> bool:
    """
    День, закрытый одним касанием: стадия `closed`, а `reviewed_at` пуст.

    Считается по паре, а не по второй колонке, — ровно как в `#143`: колонка,
    заведённая под этот же признак, рано или поздно разошлась бы с парой.
    """
    return (
        row.source == SOURCE_CLOSE
        and row.stage == STAGE_CLOSED
        and row.reviewed_at is None
    )


def render(lines: list[str]) -> str:
    """Строки отчёта одним текстом с завершающим переводом строки."""
    return "\n".join(lines).rstrip() + "\n"


def content_hash(content_md: str) -> str:
    """sha256 текста отчёта — то, чем пересборка узнаёт саму себя."""
    return hashlib.sha256(content_md.encode("utf-8")).hexdigest()


async def latest_revision(db: AsyncSession, on: date) -> DayReport | None:
    """Последняя ревизия отчёта дня, или None, если отчёта ещё не собирали."""
    result = await db.execute(
        select(DayReport)
        .where(DayReport.day_date == on)
        .order_by(DayReport.revision.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_revisions(db: AsyncSession, on: date) -> list[int]:
    """Номера всех ревизий отчёта этой даты по возрастанию."""
    result = await db.execute(
        select(DayReport.revision)
        .where(DayReport.day_date == on)
        .order_by(DayReport.revision)
    )
    return list(result.scalars().all())


async def read_revision(db: AsyncSession, on: date, revision: int) -> DayReport | None:
    """Одна названная ревизия отчёта дня."""
    result = await db.execute(
        select(DayReport).where(
            DayReport.day_date == on, DayReport.revision == revision
        )
    )
    return result.scalar_one_or_none()


async def build_report(
    db: AsyncSession, on: date, trigger: str = TRIGGER_API
) -> DayReport:
    """
    Собрать отчёт дня и записать его новой ревизией — или узнать себя и не писать.

    Совпадение `content_hash` с последней ревизией значит, что с прошлой сборки
    ничего не изменилось: возвращается та же строка, `built_at` остаётся на
    месте, вторая одинаковая ревизия не заводится. Строка дня создаётся при
    необходимости — отчёт бывает нужен дате, на которую ещё никто не заходил.
    """
    await day_crud.ensure_day(db, on)
    gathered = await _gather(db, on)
    content_md = render(gathered.lines)
    digest = content_hash(content_md)

    last = await latest_revision(db, on)
    if last is not None and last.content_hash == digest:
        return last

    report = DayReport(
        day_date=on,
        revision=0 if last is None else last.revision + 1,
        trigger=trigger,
        content_md=content_md,
        content_hash=digest,
        sources={key: fact.as_dict() for key, fact in gathered.sources.items()},
    )
    db.add(report)
    await db.flush()
    return report
