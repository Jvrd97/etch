# [review:need-review] PHASE-03/96
# summary: stored day -> `plans/YYYY/MM/YYYY-MM-DD.md` (+ `.report.md` with marks and notebook), a weekly archive writer and the CLI the cron job runs
"""
The stored day rendered back into the files it replaced.

**Why this exists at all.** ADR-0014 prices the return to the file mode at one
to two weeks, and only while a fresh human-readable slice of days exists. A
month after the switch the `.md` plans left in `personal-os` describe a canon
nobody lives under any more, and a rollback without an export loses everything
accumulated since. So this is not a feature — it is the price of the rollback,
paid weekly by `deploy/export-md.sh`.

**Two files per day, not one.** The plan goes to
`plans/YYYY/MM/YYYY-MM-DD.md` and stays a plan: front matter, an H1, sections,
items — the shape `personal-os` wrote by hand. What happened to it goes next to
it as `plans/YYYY/MM/YYYY-MM-DD.report.md`, the name `plan_server.py` already
used for the same content. Mixing the two would put ticks inside the plan text,
and the re-import of `#89` would then have to strip them back out of the very
lines it is matching on.

**The day boundary is read, never recomputed.** Windows are stored as
`timestamptz`; turning one back into `09:30` needs the zone, and the zone comes
from `app.core.daytime.current_boundary()` — the one row-backed answer of
`#107`. There is no date arithmetic in this module.

**What the export does not carry.** `plan_mark_event` (the log of every
transition), `day.kind`/`is_nocode`, `day_rule_set` and everything the later
tickets of the phase attach to a day — summaries (`#90`), work intervals
(`#91`), goals (`#93`). The export is a readable snapshot of the plan and its
outcome, not a second serialisation of the schema; the dump of
`deploy/backup.sh` is what restores the database exactly.

Related: `#89` (the importer that reads this format back), ADR-0014
(«Reversal cost»), `deploy/export-md.sh`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.daytime import current_boundary, today_local
from app.crud import day as day_crud
from app.crud import mark as mark_crud
from app.crud import plan as plan_crud
from app.models.day import Day
from app.models.journal import JournalEntry
from app.models.mark import PlanMark
from app.models.plan import DayPlan, PlanItem

__all__ = [
    "ExportedDay",
    "ExportReport",
    "PLAN_SUFFIX",
    "REPORT_SUFFIX",
    "export_day",
    "export_week",
    "main",
    "render_plan",
    "render_report",
    "week_of",
    "week_range",
]

# The two file names one day produces. `.report.md` is the name
# `plan_server.py` gave the same content, kept so a human who ran the old
# system recognises the pair without being told.
PLAN_SUFFIX = ".md"
REPORT_SUFFIX = ".report.md"

# Short weekday names, indexed by `date.weekday()`, as the live plans wrote
# them: «# План 2026-08-28 (пт)».
WEEKDAYS_RU: tuple[str, ...] = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")

# A section that lost its title still needs a heading, and a heading naming the
# kind is more use than an empty one.
SECTION_TITLE_BY_KIND: dict[str, str] = {
    "anchors": "Якоря",
    "training": "Тренировка",
    "hard_points": "Жёсткие точки дня",
    "work": "Работа",
    "study": "Учёба",
    "evening": "Вечер",
    "personal": "Личное",
    "queue": "Очередь",
    "free": "Свободный блок",
    "other": "Прочее",
}

# What a mark says, in the words the day page says it in.
MARK_TITLE_RU: dict[str, str] = {
    "done": "сделано",
    "failed": "не сделано",
    "skipped": "снято",
}

# `Подпись :: значение` — the labels that earned a column of their own, in the
# order the live plans put them in.
COLUMN_LABELS: tuple[tuple[str, str], ...] = (
    ("Ход", "plan_md"),
    ("Сделано", "done_criterion"),
    ("Почему", "why_md"),
)

# Keys whose label is not just the capitalised key.
LABEL_ALIASES: dict[str, str] = {"clickup": "ClickUp"}

# The header of the table a run of `table_row` items is rendered as. The live
# «Жёсткие точки дня» table has exactly these two columns.
TABLE_HEADER: tuple[str, str] = ("Время", "Что")

# Indent of one nesting level, in spaces — markdown needs two for a sub-bullet
# to stay part of the list above it.
INDENT = "  "


def _label_for(key: str) -> str:
    """`clickup` -> `ClickUp`, `формат` -> `Формат`."""
    alias = LABEL_ALIASES.get(key)
    if alias is not None:
        return alias
    return key[:1].upper() + key[1:]


def _value_str(value: Any) -> str:
    """
    A `Подпись :: значение` value as one line.

    Strings pass through; anything else is JSON so that a structure survives
    readable rather than as a Python `repr` nothing can parse back.
    """
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _local_time(at: datetime) -> str:
    """A stored moment as the wall clock the plan was written in."""
    zone = ZoneInfo(current_boundary().timezone)
    return at.astimezone(zone).strftime("%H:%M")


def _window_of(item: PlanItem) -> str | None:
    """`09:30-11:00, пока ногти`, or None when the line claimed no clock."""
    if item.starts_at is None or item.ends_at is None:
        return None
    window = f"{_local_time(item.starts_at)}-{_local_time(item.ends_at)}"
    if item.window_comment:
        return f"{window}, {item.window_comment}"
    return window


def _labelled_lines(item: PlanItem) -> list[tuple[str, str]]:
    """Every `Подпись :: значение` of one item, in a stable order."""
    lines: list[tuple[str, str]] = []
    window = _window_of(item)
    if window is not None:
        lines.append(("Окно", window))
    for label, attribute in COLUMN_LABELS:
        value = getattr(item, attribute)
        if value:
            lines.append((label, str(value)))
    for key in sorted(item.external_ref or {}):
        lines.append((_label_for(key), _value_str((item.external_ref or {})[key])))
    # Sorted, not insertion order: JSONB does not keep the order keys arrived
    # in, so an unsorted walk would reorder itself between two exports of the
    # same unchanged day and turn a diff of the archive into noise.
    for key in sorted(item.extra):
        lines.append((_label_for(key), _value_str(item.extra[key])))
    if item.unlinked_reason:
        lines.append(("Вне квартала", item.unlinked_reason))
    return lines


def _escape_cell(text: str) -> str:
    """A table cell cannot contain the character that separates cells."""
    return text.replace("|", "\\|").replace("\n", " ")


@dataclass
class _Node:
    """One item with the items nested under it."""

    item: PlanItem
    children: list[_Node] = field(default_factory=list)


def _nest(items: Sequence[PlanItem]) -> list[_Node]:
    """
    The flat rows of a section rebuilt into the tree they were written as.

    Two passes for the same reason `app.crud.plan._nest` needs two: `ord`
    numbers siblings among themselves, so a child at position 0 sorts ahead of
    its parent and a single pass would promote it to a root.
    """
    ordered = sorted(items, key=lambda row: row.ord)
    by_id: dict[uuid.UUID, _Node] = {row.id: _Node(item=row) for row in ordered}
    roots: list[_Node] = []
    for row in ordered:
        node = by_id[row.id]
        parent = by_id.get(row.parent_id) if row.parent_id is not None else None
        if parent is None:
            roots.append(node)
        else:
            parent.children.append(node)
    return roots


def _render_task(node: _Node, out: list[str]) -> None:
    """A work task: its own heading, then its labels, then its children."""
    item = node.item
    heading = f"{item.code} · {item.text_md}" if item.code else item.text_md
    out.append(f"### {heading}")
    out.append("")
    for label, value in _labelled_lines(item):
        out.append(f"- {label} :: {value}")
    _render_children(node, out, depth=0)
    out.append("")


def _render_bullet(node: _Node, out: list[str], depth: int, number: int | None) -> None:
    """A line of a list — a bullet, an anchor, a minimum, a numbered step."""
    item = node.item
    indent = INDENT * depth
    bullet = f"{number}." if number is not None else "-"
    text = item.text_md
    if item.kind == "minimum":
        text = f"Минимум :: {text}"
    elif item.code and item.kind in {"anchor", "hard_point"}:
        text = f"{item.code} :: {text}"
    out.append(f"{indent}{bullet} {text}")
    for label, value in _labelled_lines(item):
        out.append(f"{indent}{INDENT}- {label} :: {value}")
    _render_children(node, out, depth=depth + 1)


def _render_children(node: _Node, out: list[str], depth: int) -> None:
    """The items nested under one item, rendered at `depth`, steps numbered."""
    step_number = 0
    for child in node.children:
        if child.item.kind == "step":
            step_number += 1
            _render_bullet(child, out, depth, step_number)
        else:
            _render_bullet(child, out, depth, None)


def _render_table(nodes: Sequence[_Node], out: list[str]) -> None:
    """A run of `table_row` items as one markdown table."""
    out.append(f"| {TABLE_HEADER[0]} | {TABLE_HEADER[1]} |")
    out.append("|---|---|")
    for node in nodes:
        when = _window_of(node.item) or node.item.code or ""
        out.append(f"| {_escape_cell(when)} | {_escape_cell(node.item.text_md)} |")
    out.append("")


def _render_nodes(nodes: Sequence[_Node], out: list[str]) -> None:
    """
    The top level of a section.

    Consecutive `table_row` items collapse into one table; a `table_row`
    separated from the previous one by anything else starts a second table,
    which is what the plan looked like when it was written that way.
    """
    table_run: list[_Node] = []
    step_number = 0
    for node in nodes:
        if node.item.kind == "table_row":
            table_run.append(node)
            continue
        if table_run:
            _render_table(table_run, out)
            table_run = []
        if node.item.kind == "task":
            step_number = 0
            _render_task(node, out)
        elif node.item.kind == "step":
            step_number += 1
            _render_bullet(node, out, depth=0, number=step_number)
        else:
            step_number = 0
            _render_bullet(node, out, depth=0, number=None)
    if table_run:
        _render_table(table_run, out)


def _front_matter(plan: DayPlan) -> list[str]:
    """The `---` block: title, lede, purpose, counters — one line each."""
    out: list[str] = ["---"]
    title = plan.title
    if title and plan.title_marker:
        title = f"{title} *{plan.title_marker}*"
    if title:
        out.append(f"title: {title}")
    if plan.lede:
        out.append(f"lede: {plan.lede}")
    if plan.purpose_md:
        out.append(f"purpose: {plan.purpose_md}")
    if plan.counters:
        out.append("counters: " + "; ".join(_value_str(one) for one in plan.counters))
    if plan.condition_tomorrow:
        out.append(f"condition_tomorrow: {plan.condition_tomorrow}")
    out.append("---")
    out.append("")
    return out


def _heading(on: date) -> str:
    """`# План 2026-08-28 (пт)` — the H1 every live plan opened with."""
    return f"# План {on.isoformat()} ({WEEKDAYS_RU[on.weekday()]})"


def render_plan(on: date, plan: DayPlan) -> str:
    """
    One stored plan as the markdown a person reads.

    Deterministic by construction: sections and items by `ord`, labels in a
    fixed order, JSONB keys sorted. Two exports of an unchanged day are the same
    bytes, which is what makes the weekly archive diffable.
    """
    out: list[str] = []
    out.extend(_front_matter(plan))
    out.append(_heading(on))
    out.append("")
    for section in sorted(plan.sections, key=lambda row: row.ord):
        title = section.title or SECTION_TITLE_BY_KIND.get(section.kind, section.kind)
        out.append(f"## {title}")
        out.append("")
        _render_nodes(_nest(list(section.items)), out)
        if out and out[-1] != "":
            out.append("")
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out) + "\n"


def _mark_rows(plan: DayPlan | None, marks: Sequence[PlanMark]) -> list[str]:
    """The table of what happened, in the order the plan is read in."""
    by_item = {one.item_id: one for one in marks}
    rows: list[str] = []
    if plan is None:
        return rows
    for section in sorted(plan.sections, key=lambda row: row.ord):
        for item in sorted(section.items, key=lambda row: row.ord):
            mark = by_item.get(item.id)
            if mark is None:
                continue
            name = f"{item.code} · {item.text_plain}" if item.code else item.text_plain
            state = MARK_TITLE_RU.get(mark.state, mark.state)
            rows.append(
                f"| {_escape_cell(name)} | {state} | {_escape_cell(mark.note or '')} |"
            )
    return rows


def render_report(
    on: date,
    day: Day | None,
    plan: DayPlan | None,
    marks: Sequence[PlanMark],
    notebook: JournalEntry | None,
) -> str | None:
    """
    What happened to the plan, or None when there is nothing to say.

    None rather than an empty file on purpose: a day nobody opened is a fact the
    file mode could not record at all, and writing an empty report for it would
    put it back in the state `#88` spent a ticket getting out of.
    """
    opened = day.opened_at if day is not None else None
    if not marks and notebook is None and opened is None:
        return None

    out: list[str] = [f"# Как прошло — {on.isoformat()} ({WEEKDAYS_RU[on.weekday()]})"]
    out.append("")
    out.append(
        f"- Открыт :: {_local_time(opened)}"
        if opened is not None
        else "- Открыт :: день не открывали"
    )
    out.append("")

    rows = _mark_rows(plan, marks)
    if rows:
        out.append("## Отметки")
        out.append("")
        out.append("| Пункт | Итог | Как прошло |")
        out.append("|---|---|---|")
        out.extend(rows)
        out.append("")

    if notebook is not None and notebook.content.strip():
        out.append("## Блокнот")
        out.append("")
        out.append(notebook.content.strip())
        out.append("")

    while out and out[-1] == "":
        out.pop()
    return "\n".join(out) + "\n"


@dataclass(frozen=True)
class ExportedDay:
    """One day written out: the files, and whether there was a plan at all."""

    day_date: date
    plan_path: Path | None
    report_path: Path | None


@dataclass(frozen=True)
class ExportReport:
    """What one run of the exporter produced. Printed by the CLI, read by cron."""

    out_dir: Path
    week: str
    days: list[ExportedDay]

    @property
    def plans_written(self) -> int:
        return sum(1 for one in self.days if one.plan_path is not None)

    @property
    def reports_written(self) -> int:
        return sum(1 for one in self.days if one.report_path is not None)

    def as_lines(self) -> list[str]:
        return [
            f"week: {self.week}",
            f"out: {self.out_dir}",
            f"days: {len(self.days)}",
            f"plans: {self.plans_written}",
            f"reports: {self.reports_written}",
        ]


def week_of(on: date) -> str:
    """The ISO week a date belongs to, as `2026-W35`."""
    iso = on.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def week_range(label: str, today: date) -> tuple[date, date]:
    """
    The Monday and Sunday of a week, named by `last`, `current` or `YYYY-Www`.

    `last` is the default of the weekly cron job: on Monday morning it is the
    week that just finished, whole, and never a week still being lived.
    """
    if label == "current":
        monday = today - timedelta(days=today.weekday())
    elif label == "last":
        monday = today - timedelta(days=today.weekday() + 7)
    else:
        year_text, _, week_text = label.partition("-W")
        if not week_text.isdigit() or not year_text.isdigit():
            raise ValueError(
                f"week must be 'last', 'current' or 'YYYY-Www' (e.g. 2026-W35), "
                f"got {label!r}"
            )
        monday = date.fromisocalendar(int(year_text), int(week_text), 1)
    return monday, monday + timedelta(days=6)


def _paths_for(root: Path, on: date) -> tuple[Path, Path]:
    """`plans/2026/08/2026-08-28.md` and its report, under `root`."""
    directory = root / "plans" / f"{on.year:04d}" / f"{on.month:02d}"
    stem = on.isoformat()
    return directory / f"{stem}{PLAN_SUFFIX}", directory / f"{stem}{REPORT_SUFFIX}"


async def export_day(db: AsyncSession, on: date, root: Path) -> ExportedDay:
    """
    Write one day under `root`, and say which files it produced.

    A day with no plan writes no plan file: an empty plan on disk is
    indistinguishable from a day whose plan the export lost, and the whole point
    of the archive is that a human can trust what is in it.
    """
    day = await day_crud.get_day(db, on)
    plan = await plan_crud.get_plan(db, on)
    marks = await mark_crud.list_marks(db, on)
    notebook = await day_crud.get_notebook(db, on)

    plan_path, report_path = _paths_for(root, on)
    written_plan: Path | None = None
    written_report: Path | None = None

    if plan is not None:
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(render_plan(on, plan), encoding="utf-8")
        written_plan = plan_path

    report = render_report(on, day, plan, marks, notebook)
    if report is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")
        written_report = report_path

    return ExportedDay(day_date=on, plan_path=written_plan, report_path=written_report)


def _dates(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


async def export_week(
    db: AsyncSession, out: Path, start: date, end: date
) -> ExportReport:
    """
    Write every day of `[start, end]` into `out/<YYYY-Www>/`.

    The week folder is named after the week the range starts in, so a rerun of
    the same week overwrites its own archive instead of growing a second copy
    beside it.
    """
    label = week_of(start)
    root = out / label
    days = [await export_day(db, one, root) for one in _dates(start, end)]
    return ExportReport(out_dir=root, week=label, days=days)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.exports.personal_os",
        description=(
            "Экспорт дней из базы в `plans/YYYY/MM/*.md` — страховка отката "
            "(ADR-0014, «Reversal cost»). Запускается еженедельно из "
            "deploy/export-md.sh."
        ),
    )
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Каталог архива; внутри создаётся папка недели <YYYY-Www>",
    )
    parser.add_argument(
        "--week",
        default="last",
        help="`last` (по умолчанию — прошедшая целиком неделя), `current` или YYYY-Www",
    )
    parser.add_argument(
        "--today",
        type=date.fromisoformat,
        default=None,
        help="Точка отсчёта для `last`/`current`; по умолчанию сегодняшняя дата",
    )
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> ExportReport:
    # `today_local` needs the boundary published from the rule table, and
    # nothing has read that table in a fresh process; `list_rules` publishes it.
    async with AsyncSessionLocal() as session:
        await day_crud.list_rules(session)
        today: date = args.today or today_local()
        start, end = week_range(args.week, today)
        return await export_week(session, args.out, start, end)


def main(argv: Sequence[str] | None = None) -> int:
    """The entry point `deploy/export-md.sh` calls. Non-zero means nothing written."""
    args = _parse_args(argv)
    report = asyncio.run(_run(args))
    for line in report.as_lines():
        print(line)
    if report.plans_written == 0 and report.reports_written == 0:
        print(
            "export-md: не записано ни одного файла — "
            "либо в базе нет этой недели, либо экспорт смотрит не в ту базу",
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by deploy/export-md.sh
    raise SystemExit(main())
