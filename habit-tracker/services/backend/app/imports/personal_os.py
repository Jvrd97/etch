# [review:need-review] PHASE-03/89, PHASE-03/90, PHASE-03/93, PHASE-03/94
# summary: the idempotent CLI that moves the history of personal-os into the day tables — files hashed into `import_source`, plans written through `replace_plan`, marks matched by what a line says, summaries carried into `day_summary` with their verdicts read as prose and never recomputed, the calendar filled so no day is a hole, `goal.md` read into the goal tables by `app.imports.goal_md`, `weeks/**/*.md` read into the week snapshots by `app.imports.week_md` with the counters recomputed rather than parsed, and everything unread named in the report
"""
The history of `personal-os` moved into the database, once and repeatably.

A CLI rather than an Alembic revision, and the difference is not stylistic. The
data lives in another repository, it will be re-read several times while the
parse is being got right, and a migration is meant to run exactly once against
a schema — not to import somebody's files. ADR-0014 says the same in its
«Миграция истории» section.

**What makes a second run change nothing.** Every file is stored whole in
`import_source` with its `sha256`. A day whose files still hash to what is
stored, and whose plan is already there, is skipped entirely: no delete, no
insert, no new uuids, no moved timestamps. That is stronger than "the writes
happen to produce equal values" — the rows are not touched at all. `--force`
re-reads regardless, and then the items keep their uuids by `legacy_key`, so
the marks survive the rewrite.

**The plan is written by the one function that writes plans.**
`app.crud.plan.replace_plan` — the same validation, the same windows, the same
mark carrying as `POST /day/{date}/plan`. An import that wrote rows directly
would be the second definition of what a plan is, and the first one to drift.

**The calendar has no holes.** Every date between the first and the last plan
gets a `day` row, whether or not a plan was written for it. 16, 19 and 23-27
August exist as days nobody planned, which is a fact; a gap in the calendar
would be an absence of one.

**`opened_at` is evidence, not a side effect.** Reading a file is not a person
opening a day (`#88`), so the import sets it only where the file says a person
was there: a tick, a note, a notebook, or an explicit `Открыт ::` line in an
exported report. A day whose plan exists and whose marks are empty comes out as
«не открывал», which is the fourth kind of empty `#88` went to the trouble of
being able to express.

Run:

    uv run python -m app.imports.personal_os --root ~/Documents/MyProj/personal-os
    uv run python -m app.imports.personal_os --root … --dry-run
    uv run python -m app.imports.personal_os --root … --force --date 2026-08-28

Nothing under `--root` is written to, ever. The export in the other direction is
`app.exports.personal_os` (`#96`).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import re
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.daytime import current_boundary, day_bounds
from app.crud import day as day_crud
from app.crud import mark as mark_crud
from app.crud import plan as plan_crud
from app.crud import summary as summary_crud
from app.crud import week as week_crud
from app.day.evaluate import VERDICT_LOST, VERDICT_WON
from app.day.plan_validate import PlanRejected, resolve_window
from app.day.week import iso_code
from app.exports.personal_os import SECTION_TITLE_BY_KIND
from app.imports import goal_md
from app.imports import plan_state as state_reader
from app.imports import week_md
from app.imports.md_parser import (
    FORM_LIST_ITEM,
    FORM_TABLE_ROW,
    FORM_TASK_HEADING,
    KIND_BULLET,
    KIND_TASK,
    ParsedItem,
    ParsedPlan,
    match_key,
    parse_plan,
)
from app.models.import_source import (
    KIND_GOAL_MD,
    KIND_PLAN_HTML,
    KIND_PLAN_MD,
    KIND_PLAN_REPORT_MD,
    KIND_SUMMARY_MD,
    KIND_WEEK_MD,
    ImportSource,
)
from app.models.plan import DayPlan, PlanItem, PlanSection
from app.models.summary import SOURCE_IMPORT, DaySummary
from app.schemas.plan import PlanDocument, PlanItemIn, PlanSectionIn

__all__ = [
    "DayFiles",
    "ImportReport",
    "ImportedDay",
    "ImportWarning",
    "collect_days",
    "collect_summaries",
    "collect_weeks",
    "import_day",
    "import_root",
    "import_summary",
    "main",
    "read_verdict",
]

# `plans/2026/08/2026-08-28.md`. Anything else in that directory — a `.bak`, a
# `notes 13.08.2026.md`, the `.report.md` beside it — is matched separately or
# not at all.
PLAN_GLOB = "plans/*/*/????-??-??.md"

# `summaries/2026/08/2026-08-28.md` — the итог of a day, written by hand.
SUMMARY_GLOB = "summaries/*/*/????-??-??.md"

# `weeks/2026/2026-W35.md` — the ретро of one ISO week, written on Sunday.
WEEK_GLOB = "weeks/*/????-W??.md"

# `goal.md` — the levels, the milestones and the goals of the quarter. One file,
# at the root, and not a day: read once per run rather than per `--date`.
GOAL_FILE = "goal.md"

# The heading the verdict of a day is written under, and the reading of what is
# written there. **This is the only place in the codebase that parses a verdict
# out of prose** — `evaluate_day`, the crud and the API all work with the value.
#
# The bold fragment is searched *inside*, not matched from its start: `life.py`
# used `\*\*(да|нет)` and «**Формально — нет.**» — the verdict of 28 August —
# fell through it into "nobody judged this day", which is a different fact and
# the wrong one. A line with no bold at all («Вне игры (выходной)») still has no
# verdict, and that is right: nothing judged that day either.
VERDICT_HEAD_RE = re.compile(r"^##\s*День выигран\?\s*$", re.MULTILINE)
VERDICT_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
VERDICT_VALUE_RE = re.compile(r"\b(да|нет)\b", re.IGNORECASE)
VERDICT_BY_WORD = {"да": VERDICT_WON, "нет": VERDICT_LOST}

# Written into `plan_item.unlinked_reason` for every imported task. A task has to
# name a quarter goal or the reason it names none (`#87`), and the goals
# themselves arrive with `#93`: until then the honest answer is this one, said
# out loud on every row, rather than a goal id invented during an import.
IMPORT_UNLINKED_REASON = (
    "импорт истории personal-os: цели квартала приезжают отдельным срезом (#93)"
)

# `plan_item.source` of a plan that came from a file rather than from /day-open.
PLAN_SOURCE = "import"
MARK_SOURCE = "import"

# Prefix of the `legacy_key` given to a line the rendered page never marked —
# it has no `i7` of its own, and it still has to be recognisable on a re-run.
POSITION_KEY_PREFIX = "md"

# A link to another plan of the same repository becomes a link to the day it is.
# Everything else relative (`../../../weeks/…`, `goal.md`) has no screen to point
# at yet and is named in the report instead of being rewritten into a dead url.
PLAN_LINK_RE = re.compile(r"\]\((?:\./)?(\d{4}-\d{2}-\d{2})\.md\)")
# `[ретро](../../weeks/2026/2026-W35.md)` — a week now has a screen (`#94`).
WEEK_LINK_RE = re.compile(r"\]\([./]*weeks/\d{4}/(\d{4}-W\d{2})\.md\)")
RELATIVE_LINK_RE = re.compile(r"\]\((?!https?://|/|#)([^)]+)\)")


@dataclass(frozen=True)
class DayFiles:
    """The files one day of `personal-os` is made of."""

    day_date: date
    plan_md: Path
    plan_html: Path | None
    report_md: Path | None

    def paths(self) -> list[tuple[str, Path]]:
        found = [(KIND_PLAN_MD, self.plan_md)]
        if self.plan_html is not None:
            found.append((KIND_PLAN_HTML, self.plan_html))
        if self.report_md is not None:
            found.append((KIND_PLAN_REPORT_MD, self.report_md))
        return found


@dataclass(frozen=True)
class ImportWarning:
    """Something the import could not do quietly, named where it happened."""

    kind: str
    message: str
    path: str | None = None
    key: str | None = None

    def as_line(self) -> str:
        where = self.path or ""
        if self.key:
            where = f"{where}#{self.key}" if where else self.key
        tail = f" [{where}]" if where else ""
        return f"  {self.kind}: {self.message}{tail}"


@dataclass
class ImportedDay:
    """What happened to one day."""

    day_date: date
    action: str
    sections: int = 0
    items: int = 0
    marks: int = 0
    notebook: bool = False
    reason: str | None = None


@dataclass
class ImportReport:
    """What one run of the importer did. Printed by the CLI, read by a human."""

    root: Path
    dry_run: bool = False
    days: list[ImportedDay] = field(default_factory=list)
    gaps_filled: list[date] = field(default_factory=list)
    warnings: list[ImportWarning] = field(default_factory=list)
    files_read: int = 0
    # Summaries are counted apart from days: a day is a plan, and a summary can
    # exist for a date that never had one (20 August was a day off).
    summaries_written: int = 0
    summaries_unchanged: int = 0
    # `goal.md` is one file rather than a countable set, so it reports as a
    # yes/no: it was read, it was already current, or the repository has none.
    goals_written: bool = False
    goals_unchanged: bool = False
    # Weeks are counted apart from days for the reason summaries are: a week
    # exists (and is recomputed) whether or not anybody wrote a ретро for it.
    weeks_written: int = 0
    weeks_unchanged: int = 0
    weeks_recomputed: int = 0
    # Week codes the run read a file for; the recompute adds the weeks of every
    # imported day to these before it takes the counters.
    touched_weeks: set[str] = field(default_factory=set)

    def _count(self, action: str) -> int:
        return sum(1 for one in self.days if one.action == action)

    @property
    def written(self) -> int:
        return self._count("written")

    @property
    def unchanged(self) -> int:
        return self._count("unchanged")

    @property
    def failed(self) -> int:
        return self._count("failed")

    @property
    def items_written(self) -> int:
        return sum(one.items for one in self.days)

    @property
    def marks_written(self) -> int:
        return sum(one.marks for one in self.days)

    def as_lines(self) -> list[str]:
        return [
            f"root: {self.root}",
            f"dry-run: {'да' if self.dry_run else 'нет'}",
            f"файлов прочитано: {self.files_read}",
            f"дней с планом: {len(self.days)}",
            f"записано: {self.written}",
            f"без изменений: {self.unchanged}",
            f"отказано: {self.failed}",
            f"пунктов: {self.items_written}",
            f"отметок: {self.marks_written}",
            f"итогов записано: {self.summaries_written}",
            f"итогов без изменений: {self.summaries_unchanged}",
            f"goal.md: {_goal_state(self)}",
            f"недель записано: {self.weeks_written}",
            f"недель без изменений: {self.weeks_unchanged}",
            f"недель пересчитано: {self.weeks_recomputed}",
            f"дней без плана заведено: {len(self.gaps_filled)}",
            f"предупреждений: {len(self.warnings)}",
        ]


def _goal_state(report: ImportReport) -> str:
    """How the run treated `goal.md`, in one word for the CLI."""
    if report.goals_written:
        return "прочитан"
    if report.goals_unchanged:
        return "без изменений"
    return "нет файла"


def collect_days(root: Path) -> list[DayFiles]:
    """
    Every day `root` has a plan for, oldest first.

    A file is a plan when its name is a date and nothing else. `2026-08-18.md.bak`
    and `notes 13.08.2026.md` are in the same directory and are neither.
    """
    found: list[DayFiles] = []
    for path in sorted(root.glob(PLAN_GLOB)):
        try:
            day_date = date.fromisoformat(path.stem)
        except ValueError:
            continue
        html = path.with_suffix(".html")
        report = path.with_name(f"{path.stem}.report.md")
        found.append(
            DayFiles(
                day_date=day_date,
                plan_md=path,
                plan_html=html if html.exists() else None,
                report_md=report if report.exists() else None,
            )
        )
    return found


def collect_summaries(root: Path) -> list[tuple[date, Path]]:
    """Every day `root` has an итог for, oldest first."""
    found: list[tuple[date, Path]] = []
    for path in sorted(root.glob(SUMMARY_GLOB)):
        try:
            found.append((date.fromisoformat(path.stem), path))
        except ValueError:
            continue
    return found


def collect_weeks(root: Path) -> list[tuple[str, Path]]:
    """
    Every `weeks/**/*.md` whose name is an ISO week code, oldest first.

    A file whose name is not a week code is left alone rather than guessed at:
    the week is keyed by that code, and a wrong guess would put a ретро on a
    week it does not describe.
    """
    found: list[tuple[str, Path]] = []
    for path in sorted(root.glob(WEEK_GLOB)):
        iso = week_md.iso_from_name(path.stem)
        if iso is not None:
            found.append((iso, path))
    return found


def read_verdict(text: str) -> str | None:
    """
    The verdict a summary states, or None when it states none.

    Looks under `## День выигран?` for the first bold fragment of the first line
    that has one, and for да/нет inside it. «**Формально — нет.**» is a verdict;
    «Вне игры (выходной)» is not, and answering `lost` for it would invent a
    loss on a day that was deliberately outside the game.
    """
    head = VERDICT_HEAD_RE.search(text)
    if head is None:
        return None
    # Only as far as the next heading: the sentence about the streak two
    # paragraphs down is about a different day.
    section = text[head.end() :].split("\n## ", 1)[0]
    for bold in VERDICT_BOLD_RE.finditer(section):
        word = VERDICT_VALUE_RE.search(bold.group(1))
        if word is not None:
            return VERDICT_BY_WORD[word.group(1).lower()]
    return None


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def _stored_digests(db: AsyncSession, paths: Iterable[str]) -> dict[str, str]:
    wanted = list(paths)
    if not wanted:
        return {}
    result = await db.execute(
        select(ImportSource.path, ImportSource.sha256).where(
            ImportSource.path.in_(wanted)
        )
    )
    return {row.path: row.sha256 for row in result}


async def _remember_file(
    db: AsyncSession, *, kind: str, path: str, text: str, digest: str
) -> None:
    """Keep the file itself, by path, replacing what was last read there."""
    statement = pg_insert(ImportSource).values(
        id=uuid.uuid4(),
        kind=kind,
        path=path,
        sha256=digest,
        imported_at=datetime.now(timezone.utc),
        raw=text,
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[ImportSource.path],
            set_={
                "kind": statement.excluded.kind,
                "sha256": statement.excluded.sha256,
                "imported_at": statement.excluded.imported_at,
                "raw": statement.excluded.raw,
            },
        )
    )


def _rewrite_links(text: str, warnings: list[ImportWarning], where: str) -> str:
    """
    Relative links of `personal-os` as links of the application.

    `[завтра](2026-08-31.md)` is a day and becomes `/day/2026-08-31`; a link into
    `weeks/` is a week and becomes `/week/2026-W35`. A link into `summaries/`,
    `docs/` or `goal.md` has no screen of its own, so it stays the text it was
    and says so in the report — a rewritten link to a page that does not exist
    would be worse than an unrewritten one.
    """
    rewritten = WEEK_LINK_RE.sub(r"](/week/\1)", text)
    rewritten = PLAN_LINK_RE.sub(r"](/day/\1)", rewritten)
    for match in RELATIVE_LINK_RE.finditer(rewritten):
        warnings.append(
            ImportWarning(
                kind="ссылка не переписана",
                message=f"относительная ссылка «{match.group(1)}» осталась текстом",
                path=where,
            )
        )
    return rewritten


def _item_kind_for(item: ParsedItem, warnings: list[ImportWarning], where: str) -> str:
    """
    The kind a parsed line is stored under.

    A `### W1 · …` heading is a task only when it carries the window and the
    criterion the canon of 2026-08-28 requires. The ones that do not — every work
    line before that date — stay bullets, keep their text and stop counting
    against the bar of four. The downgrade is reported; doing it quietly would
    make «в плане 5 задач» impossible to see in the history.
    """
    if item.kind != KIND_TASK:
        return item.kind
    if item.window and item.done_criterion:
        return KIND_TASK
    missing = "окна" if not item.window else "критерия «Сделано»"
    warnings.append(
        ImportWarning(
            kind="задача понижена до пункта",
            message=f"у «{item.code or item.text_md}» нет {missing}",
            path=where,
        )
    )
    return KIND_BULLET


def _unlinked_reason(item: ParsedItem, kind: str) -> str | None:
    """
    Why this task names no quarter goal.

    The file's own answer when it has one — an exported day carries it as
    `Вне квартала ::` — and otherwise the one sentence true of every imported
    task. A task without either is refused by `#87`, and inventing a goal id
    during an import would be worse than saying this out loud on every row.
    """
    if kind != KIND_TASK:
        return item.unlinked_reason
    return item.unlinked_reason or IMPORT_UNLINKED_REASON


def _to_item_in(
    item: ParsedItem,
    *,
    warnings: list[ImportWarning],
    where: str,
    ids: dict[str, uuid.UUID],
    codes: set[str],
) -> PlanItemIn:
    kind = _item_kind_for(item, warnings, where)
    text = item.text_md
    code = item.code
    if kind != KIND_TASK and item.kind == KIND_TASK and code:
        # A downgraded task keeps its handle where the export can carry it. The
        # `code` column of a bullet is not rendered by `app.exports.personal_os`
        # (only tasks and table rows have a place for it), so «W3» would be lost
        # on the way out and the day would come back a line poorer.
        text = f"{code} · {text}"
        code = None
    extra = dict(item.extra)
    if code is not None:
        if code in codes:
            # `UNIQUE(section_id, code) WHERE code IS NOT NULL`: two rows of one
            # section cannot share a handle. The loser keeps its text in `extra`
            # rather than losing it.
            extra.setdefault("Метка", code)
            warnings.append(
                ImportWarning(
                    kind="повтор кода",
                    message=f"«{code}» встречается в разделе дважды, второй ушёл в extra",
                    path=where,
                )
            )
            code = None
        else:
            codes.add(code)

    return PlanItemIn(
        id=ids.get(item.legacy_key or ""),
        kind=kind,
        text_md=_rewrite_links(text, warnings, where),
        window=item.window,
        window_comment=item.window_comment,
        code=code,
        done_criterion=item.done_criterion,
        why_md=item.why_md,
        plan_md=(
            _rewrite_links(item.plan_md, warnings, where)
            if item.plan_md is not None
            else None
        ),
        external_ref=item.external_ref,
        extra=extra,
        unlinked_reason=_unlinked_reason(item, kind),
        legacy_key=item.legacy_key,
        children=[
            _to_item_in(child, warnings=warnings, where=where, ids=ids, codes=codes)
            for child in item.children
        ],
    )


def build_document(
    plan: ParsedPlan,
    *,
    warnings: list[ImportWarning],
    where: str,
    ids: dict[str, uuid.UUID],
) -> PlanDocument:
    """A parsed plan as the document `replace_plan` accepts."""
    sections: list[PlanSectionIn] = []
    for section in plan.sections:
        codes: set[str] = set()
        sections.append(
            PlanSectionIn(
                # An untitled section is the prose above the first `##`. The
                # exporter has to give it a heading to write it out, and it uses
                # the name of its kind — so the import names it the same way and
                # a day exported and read back is the day it was.
                title=section.title
                or SECTION_TITLE_BY_KIND.get(section.kind, section.kind),
                kind=section.kind,
                items=[
                    _to_item_in(
                        item, warnings=warnings, where=where, ids=ids, codes=codes
                    )
                    for item in section.items
                ],
            )
        )
    return PlanDocument(
        title=plan.title,
        title_marker=plan.title_marker,
        lede=plan.lede,
        purpose_md=plan.purpose_md,
        counters=list(plan.counters),
        condition_tomorrow=plan.condition_tomorrow,
        source=PLAN_SOURCE,
        raw_md=plan.raw_md,
        sections=sections,
    )


@dataclass
class _Binding:
    """One mark of the page, and the line it was made against."""

    key: str
    item: ParsedItem
    state: str | None
    note: str | None
    via_alias: bool = False


def bind_marks(
    plan: ParsedPlan,
    state: state_reader.PlanState,
    *,
    warnings: list[ImportWarning],
    where: str,
) -> list[_Binding]:
    """
    Every mark of the rendered page put back on the line it belongs to.

    Matched by what the line says, family by family: a list item to a list item,
    a table row to a table row, a task heading to a task heading. A row of the
    generated schedule is an alias of the line it lists, honoured only when that
    line has no mark of its own. Anything that matches nothing is named in the
    report with its key and its file — and stays in `import_source.raw`.
    """
    by_form: dict[str, dict[str, list[ParsedItem]]] = {}
    for item in plan.items():
        if item.html_form is None:
            continue
        by_form.setdefault(item.html_form, {}).setdefault(item.signature(), []).append(
            item
        )
    anywhere: dict[str, list[ParsedItem]] = {}
    for item in plan.items():
        anywhere.setdefault(item.signature(), []).append(item)
        # A schedule row of a hard point carries only the second column of the
        # row it was built from — the time went into a column of its own — so a
        # table row has to be findable by its text alone as well.
        if item.html_form == FORM_TABLE_ROW:
            anywhere.setdefault(match_key(item.text_md), []).append(item)

    direct: list[_Binding] = []
    aliases: list[_Binding] = []

    for row in state.keys:
        mark = state.marks.get(row.key)
        if mark is None:
            continue
        if row.form == state_reader.FORM_TASK_LINK:
            _bind_task_link(row, mark, by_form, warnings, where)
            continue

        candidates = _candidates(row, by_form, anywhere)
        line = _take(candidates, row.key, alias=row.alias_of is not None)
        if line is None:
            warnings.append(
                ImportWarning(
                    kind="отметка без пункта",
                    message=(
                        f"состояние «{mark.state or 'заметка'}» не село ни на один "
                        "пункт: строка есть в .html, но не в .md"
                    ),
                    path=where,
                    key=row.key,
                )
            )
            continue
        binding = _Binding(
            key=row.key,
            item=line,
            state=mark.state,
            note=(mark.note or "").strip() or None,
            via_alias=row.alias_of is not None,
        )
        (aliases if binding.via_alias else direct).append(binding)

    marked = {id(one.item) for one in direct}
    kept = list(direct)
    for alias in aliases:
        if id(alias.item) in marked:
            warnings.append(
                ImportWarning(
                    kind="расписание спорит со строкой",
                    message=(
                        "строка расписания отмечена иначе, чем сам пункт; взята "
                        "отметка пункта"
                    ),
                    path=where,
                    key=alias.key,
                )
            )
            continue
        marked.add(id(alias.item))
        kept.append(alias)
    return kept


def _candidates(
    row: state_reader.KeyRow,
    by_form: dict[str, dict[str, list[ParsedItem]]],
    anywhere: dict[str, list[ParsedItem]],
) -> list[ParsedItem]:
    if row.alias_of is None:
        forms = {
            state_reader.FORM_LIST_ITEM: FORM_LIST_ITEM,
            state_reader.FORM_TABLE_ROW: FORM_TABLE_ROW,
            state_reader.FORM_TASK_HEADING: FORM_TASK_HEADING,
        }
        return by_form.get(forms[row.form], {}).get(row.signature, [])
    # A schedule row names its source by the text of one cell: the whole heading
    # for a task, only the second column for a hard point. Both are looked up
    # among every line of the day rather than within one family.
    return anywhere.get(row.alias_of, [])


def _take(candidates: list[ParsedItem], key: str, *, alias: bool) -> ParsedItem | None:
    """
    The line a key points at.

    A direct key claims the first line nothing has claimed yet, and the line
    keeps that key as its `legacy_key` — two identical lines on one page then get
    one mark each rather than both getting the first one. An alias claims
    nothing: it names a line that already exists elsewhere on the page, and
    whether its mark is used at all is decided afterwards.
    """
    if alias:
        return candidates[0] if candidates else None
    for candidate in candidates:
        if candidate.legacy_key is None:
            candidate.legacy_key = key
            return candidate
    return None


def _bind_task_link(
    row: state_reader.KeyRow,
    mark: state_reader.StateMark,
    by_form: dict[str, dict[str, list[ParsedItem]]],
    warnings: list[ImportWarning],
    where: str,
) -> None:
    """A url typed into the ClickUp slot of a task becomes its `external_ref`."""
    url = (mark.note or "").strip()
    if not url:
        return
    found = by_form.get(FORM_TASK_HEADING, {}).get(row.signature, [])
    if not found:
        warnings.append(
            ImportWarning(
                kind="ссылка без задачи",
                message=f"ссылка ClickUp «{url}» не села ни на одну задачу",
                path=where,
                key=row.key,
            )
        )
        return
    reference = dict(found[0].external_ref or {})
    reference.setdefault("clickup", url)
    found[0].external_ref = reference


def assign_position_keys(plan: ParsedPlan) -> None:
    """
    Give every line that has no key of its own a stable positional one.

    `legacy_key` is what a re-run recognises a row by, so a line the rendered
    page never marked still needs one. `md:2.0.1` is section, item, child — a
    handle nobody has to guess and nothing else can collide with, since the keys
    of the page are `i7`, `t3`, `w0`.
    """
    for section_index, section in enumerate(plan.sections):
        for path, item in _walk_positions(section.items):
            if item.legacy_key is None:
                item.legacy_key = f"{POSITION_KEY_PREFIX}:{section_index}.{path}"


def _walk_positions(
    items: Sequence[ParsedItem], prefix: str = ""
) -> Iterable[tuple[str, ParsedItem]]:
    for index, item in enumerate(items):
        path = f"{prefix}{index}"
        yield path, item
        yield from _walk_positions(item.children, prefix=f"{path}.")


async def _has_plan(db: AsyncSession, on: date) -> bool:
    """
    Whether `on` already has a plan.

    A scalar rather than `get_plan`: the answer is needed for every day of the
    repository on every run, and loading the whole tree of a day that is about to
    be skipped puts its rows into the identity map for no reason.
    """
    result = await db.execute(select(DayPlan.id).where(DayPlan.day_date == on))
    return result.scalar_one_or_none() is not None


async def _stored_ids(db: AsyncSession, on: date) -> dict[str, uuid.UUID]:
    """`legacy_key` to the uuid it already has, for the plan stored on `on`."""
    result = await db.execute(
        select(PlanItem.legacy_key, PlanItem.id)
        .join(PlanSection, PlanSection.id == PlanItem.section_id)
        .join(DayPlan, DayPlan.id == PlanSection.plan_id)
        .where(DayPlan.day_date == on, PlanItem.legacy_key.is_not(None))
    )
    return {row.legacy_key: row.id for row in result if row.legacy_key}


async def import_day(
    db: AsyncSession,
    files: DayFiles,
    *,
    root: Path,
    warnings: list[ImportWarning],
) -> ImportedDay:
    """Read one day's files and write the day, its plan, its marks and its notebook."""
    on = files.day_date
    where = str(files.plan_md.relative_to(root))
    text = files.plan_md.read_text(encoding="utf-8")
    plan = parse_plan(text, on)
    for line in plan.unparsed:
        warnings.append(
            ImportWarning(kind="не разобрано", message=line.splitlines()[0], path=where)
        )

    state: state_reader.PlanState | None = None
    if files.plan_html is not None:
        state = state_reader.read_plan_state(
            files.plan_html.read_text(encoding="utf-8")
        )
        if state is None:
            warnings.append(
                ImportWarning(
                    kind="страница без отметок",
                    message="в .html нет блока plan-state — день не открывали в сервере",
                    path=str(files.plan_html.relative_to(root)),
                )
            )

    bindings: list[_Binding] = []
    if state is not None:
        bindings = bind_marks(
            plan,
            state,
            warnings=warnings,
            where=str(
                files.plan_html.relative_to(root) if files.plan_html else files.plan_md
            ),
        )

    report = _read_report(files, root, warnings)
    assign_position_keys(plan)

    await day_crud.ensure_day(db, on)
    rule = await day_crud.rule_for_date(db, on)
    ids = await _stored_ids(db, on)
    document = build_document(plan, warnings=warnings, where=where, ids=ids)

    try:
        stored = await plan_crud.replace_plan(db, on, rule, document)
    except PlanRejected as rejected:
        warnings.append(
            ImportWarning(kind="план отвергнут", message=rejected.message, path=where)
        )
        return ImportedDay(day_date=on, action="failed", reason=rejected.error)

    marks_written = await _apply_marks(
        db, on, stored, bindings, report, warnings, where
    )
    notebook = _notebook_of(state, report)
    if notebook:
        await day_crud.set_notebook(db, on, notebook)

    await _record_opened(db, on, bindings, report, notebook)
    for kind, path in files.paths():
        raw = path.read_text(encoding="utf-8")
        await _remember_file(
            db,
            kind=kind,
            path=str(path.relative_to(root)),
            text=raw,
            digest=_digest(raw),
        )

    return ImportedDay(
        day_date=on,
        action="written",
        sections=len(stored.sections),
        items=sum(len(section.items) for section in stored.sections),
        marks=marks_written,
        notebook=bool(notebook),
    )


def _read_report(
    files: DayFiles, root: Path, warnings: list[ImportWarning]
) -> state_reader.DayReport | None:
    if files.report_md is None:
        return None
    text = files.report_md.read_text(encoding="utf-8")
    report = state_reader.read_day_report(text)
    if report is None:
        warnings.append(
            ImportWarning(
                kind="чужой .report.md",
                message=(
                    "отчёт написан не экспортёром (plan_server.py) — его списки "
                    "производны от .html, отметки берутся оттуда"
                ),
                path=str(files.report_md.relative_to(root)),
            )
        )
    return report


def _notebook_of(
    state: state_reader.PlanState | None, report: state_reader.DayReport | None
) -> str | None:
    if report is not None and report.notebook:
        return report.notebook
    if state is not None and state.notebook:
        return state.notebook
    return None


async def _apply_marks(
    db: AsyncSession,
    on: date,
    stored: DayPlan,
    bindings: list[_Binding],
    report: state_reader.DayReport | None,
    warnings: list[ImportWarning],
    where: str,
) -> int:
    """Put every bound mark on the row that now carries the line."""
    by_legacy: dict[str, uuid.UUID] = {}
    by_signature: dict[str, uuid.UUID] = {}
    for section in stored.sections:
        for item in section.items:
            if item.legacy_key:
                by_legacy[item.legacy_key] = item.id
            name = f"{item.code} · {item.text_plain}" if item.code else item.text_plain
            by_signature.setdefault(match_key(name), item.id)
            by_signature.setdefault(match_key(item.text_plain), item.id)

    written = 0
    for binding in bindings:
        if binding.state is None:
            continue
        item_id = by_legacy.get(binding.item.legacy_key or "")
        if item_id is None:
            warnings.append(
                ImportWarning(
                    kind="отметка потеряла пункт",
                    message="пункт не сохранился под своим ключом",
                    path=where,
                    key=binding.key,
                )
            )
            continue
        await mark_crud.set_mark(
            db, on, item_id, state=binding.state, note=binding.note, source=MARK_SOURCE
        )
        written += 1

    if report is not None:
        written += await _apply_reported(db, on, report, by_signature, warnings, where)
    return written


async def _apply_reported(
    db: AsyncSession,
    on: date,
    report: state_reader.DayReport,
    by_signature: dict[str, uuid.UUID],
    warnings: list[ImportWarning],
    where: str,
) -> int:
    """Marks named by an exported `.report.md`, matched by the text of the line."""
    written = 0
    for reported in report.marks:
        item_id = by_signature.get(reported.signature)
        if item_id is None:
            warnings.append(
                ImportWarning(
                    kind="отметка без пункта",
                    message=f"строка отчёта «{reported.signature[:40]}» не нашла пункт",
                    path=where,
                )
            )
            continue
        await mark_crud.set_mark(
            db,
            on,
            item_id,
            state=reported.state,
            note=reported.note,
            source=MARK_SOURCE,
        )
        written += 1
    return written


async def _record_opened(
    db: AsyncSession,
    on: date,
    bindings: list[_Binding],
    report: state_reader.DayReport | None,
    notebook: str | None,
) -> None:
    """
    Set `opened_at` where the files say a person was there, and only there.

    The moment is the one the file names (`Открыт :: 08:12` in an exported
    report) or, when a tick is all the evidence there is, the start of the day
    itself: the `.html` records that the day was worked, never at what hour. A
    guess inside the day is a fact about the right day; `now()` would be a fact
    about the import.
    """
    opened_at: datetime | None = None
    if report is not None and report.opened_at_local is not None:
        opened_at = _pin_local(on, report.opened_at_local)
    elif bindings or notebook:
        opened_at = day_bounds(on)[0]

    day = await day_crud.get_day(db, on)
    if day is None:  # pragma: no cover - ensure_day ran a few lines above
        return
    if opened_at is not None and day.opened_at is None:
        day.opened_at = opened_at
    await day_crud.touch_day(db, day, opened=False)


def _pin_local(on: date, at: time) -> datetime:
    """A wall-clock time of the day `on`, as the moment it was."""
    return resolve_window(on, at, at, current_boundary()).starts_at


async def import_summary(
    db: AsyncSession,
    on: date,
    path: Path,
    *,
    root: Path,
    warnings: list[ImportWarning],
) -> None:
    """
    Read one `summaries/**/*.md` into `day_summary` as it is written.

    **Вердикт переносится, а не пересчитывается.** The row is marked
    `source='import'`, and `recompute_history` never rewrites the judgement of
    such a row: the day it describes has no marks and no measured work, so
    re-judging it would replace a person's sentence with zeros. Смена канона
    2026-08-17 иначе переписала бы задним числом всё, что было до неё.

    `rule_set_id` is the rule that was in force on the date — the same one
    `day.rule_set_id` carries — rather than the `legacy` row ADR-0014 names. 20
    and 28 August were lived under the current canon, and pointing them at
    `legacy` would make one date claim two different canons. "Не пересчитывать"
    is what `source` expresses, and it holds for every date rather than only for
    the ones before the change.

    The counters stay at zero and `work_minutes` at NULL on purpose: nothing
    counted them, and a zero that means "не измерено" is the lie this schema is
    built to avoid. The numbers a person did write are in `body_md`.
    """
    where = str(path.relative_to(root))
    text = path.read_text(encoding="utf-8")
    day = await day_crud.ensure_day(db, on)
    rule = await day_crud.rule_for_date(db, on)

    values = {
        "day_date": day.day_date,
        "rule_set_id": rule.id,
        "verdict": read_verdict(text),
        "verdict_reason": "",
        "body_md": _rewrite_links(text, warnings, where),
        "source": SOURCE_IMPORT,
    }
    statement = pg_insert(DaySummary).values(**values)
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[DaySummary.day_date],
            set_={key: statement.excluded[key] for key in values if key != "day_date"},
        )
    )
    await _remember_file(
        db, kind=KIND_SUMMARY_MD, path=where, text=text, digest=_digest(text)
    )
    await db.flush()


async def import_root(
    db: AsyncSession,
    root: Path,
    *,
    force: bool = False,
    only: date | None = None,
) -> ImportReport:
    """
    Read every plan under `root` and put the days it describes into the database.

    Nothing under `root` is written to. A day whose files have not changed since
    the last run, and whose plan is stored, is left exactly as it is.
    """
    report = ImportReport(root=root)
    days = [one for one in collect_days(root) if only is None or one.day_date == only]

    for files in days:
        report.files_read += len(files.paths())
        digests = {
            str(path.relative_to(root)): _digest(path.read_text(encoding="utf-8"))
            for _, path in files.paths()
        }
        stored = await _stored_digests(db, digests)
        if not force and await _has_plan(db, files.day_date) and stored == digests:
            report.days.append(ImportedDay(day_date=files.day_date, action="unchanged"))
            continue
        report.days.append(
            await import_day(db, files, root=root, warnings=report.warnings)
        )

    report.gaps_filled = await _fill_calendar(db, [one.day_date for one in days])
    await _import_summaries(db, root, report, force=force, only=only)
    await _import_goals(db, root, report, force=force)
    await _import_weeks(db, root, report, force=force, only=only)
    # Fills `streak_after` on every итог, imported ones included: the streak is
    # derived by definition, so it is the one number a recompute may write onto
    # a verdict that arrived as prose.
    await summary_crud.recompute_history(db)
    # And only then the weeks: `streak_end` is `streak_after` of the last closed
    # day of the week, so a week counted before the fold would carry the streak
    # of the previous run.
    await _recompute_weeks(db, report)
    return report


async def _import_weeks(
    db: AsyncSession,
    root: Path,
    report: ImportReport,
    *,
    force: bool,
    only: date | None,
) -> None:
    """
    Read every `weeks/**/*.md`, skipping the files that have not changed.

    `--date` narrows this to the week that date falls in: a week is not a day,
    but it is the week of a day, and re-reading every ретро in the repository to
    import one Tuesday would be surprising.
    """
    wanted = None if only is None else iso_code(only)
    for iso, path in collect_weeks(root):
        if wanted is not None and iso != wanted:
            continue
        report.files_read += 1
        where = str(path.relative_to(root))
        text = path.read_text(encoding="utf-8")
        digest = _digest(text)
        stored = await _stored_digests(db, [where])
        if not force and stored.get(where) == digest:
            report.weeks_unchanged += 1
            report.touched_weeks.add(iso)
            continue
        parsed = week_md.parse_week(iso, _rewrite_links(text, report.warnings, where))
        await week_crud.replace_week_text(db, iso, parsed.as_body())
        await _remember_file(
            db, kind=KIND_WEEK_MD, path=where, text=text, digest=digest
        )
        report.weeks_written += 1
        report.touched_weeks.add(iso)


async def _recompute_weeks(db: AsyncSession, report: ImportReport) -> None:
    """
    Take the counters of every week the run touched, days included.

    A week whose ретро nobody wrote still gets a row here: the days of it exist
    and were won or lost, and `/life` has to be able to open that week. This is
    also where «неделя без ретро существует» stops being a claim and becomes a
    row.
    """
    weeks = set(report.touched_weeks)
    weeks.update(iso_code(one.day_date) for one in report.days)
    weeks.update(iso_code(one) for one in report.gaps_filled)
    for iso in sorted(weeks):
        await week_crud.recompute_week(db, iso)
    report.weeks_recomputed = len(weeks)


async def _import_summaries(
    db: AsyncSession,
    root: Path,
    report: ImportReport,
    *,
    force: bool,
    only: date | None,
) -> None:
    """Read every `summaries/**/*.md`, skipping the files that have not changed."""
    for on, path in collect_summaries(root):
        if only is not None and on != only:
            continue
        report.files_read += 1
        where = str(path.relative_to(root))
        digest = _digest(path.read_text(encoding="utf-8"))
        stored = await _stored_digests(db, [where])
        known = await summary_crud.get_summary(db, on) is not None
        if not force and known and stored.get(where) == digest:
            report.summaries_unchanged += 1
            continue
        await import_summary(db, on, path, root=root, warnings=report.warnings)
        report.summaries_written += 1


async def _import_goals(
    db: AsyncSession, root: Path, report: ImportReport, *, force: bool
) -> None:
    """
    Read `goal.md`, unless it is not there or has not changed since the last run.

    Not tied to `--date`: the goals are not a day. A repository without the file
    imports its days as before — the goals are one part of `personal-os`, not a
    precondition for the rest of it.
    """
    path = root / GOAL_FILE
    if not path.is_file():
        return
    report.files_read += 1
    where = str(path.relative_to(root))
    text = path.read_text(encoding="utf-8")
    digest = _digest(text)
    stored = await _stored_digests(db, [where])
    if not force and stored.get(where) == digest:
        report.goals_unchanged = True
        return
    await goal_md.import_goals(db, text)
    await _remember_file(db, kind=KIND_GOAL_MD, path=where, text=text, digest=digest)
    await db.flush()
    report.goals_written = True


async def _fill_calendar(db: AsyncSession, known: Sequence[date]) -> list[date]:
    """
    Every date between the first and the last plan exists as a day.

    A day with no plan is a day nobody planned — 16, 19 and 23-27 August are
    such — and that is a different statement from a hole in the calendar, which
    is what the file mode left behind.
    """
    if not known:
        return []
    filled: list[date] = []
    planned = set(known)
    current, last = min(known), max(known)
    while current <= last:
        if current not in planned:
            existed = await day_crud.get_day(db, current) is not None
            await day_crud.ensure_day(db, current)
            if not existed:
                filled.append(current)
        current += timedelta(days=1)
    return filled


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.imports.personal_os",
        description=(
            "Импорт истории personal-os в таблицы дня. Идемпотентен: повторный "
            "прогон не трогает ни одной строки. Файлы репозитория только читаются."
        ),
    )
    parser.add_argument(
        "--root", required=True, type=Path, help="Корень репозитория personal-os"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Разобрать и посчитать, но не записывать: транзакция откатывается",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Перечитать день, даже если файлы не менялись",
    )
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        default=None,
        help="Только один день, YYYY-MM-DD",
    )
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> ImportReport:
    root: Path = args.root.expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"нет каталога {root}")
    async with AsyncSessionLocal() as session:
        # `rule_for_date` publishes the day boundary from the rule table; nothing
        # has read it in a fresh process, and every window of every plan needs it.
        await day_crud.list_rules(session)
        report = await import_root(session, root, force=args.force, only=args.date)
        report.dry_run = args.dry_run
        if args.dry_run:
            await session.rollback()
        else:
            await session.commit()
        return report


def main(argv: Sequence[str] | None = None) -> int:
    """The entry point of `python -m app.imports.personal_os`."""
    args = _parse_args(argv)
    report = asyncio.run(_run(args))
    for line in report.as_lines():
        print(line)
    for warning in report.warnings:
        print(warning.as_line())
    if report.failed:
        print(f"import: {report.failed} дней не записано — см. предупреждения выше")
        return 1
    if not report.days:
        print("import: под --root не нашлось ни одного plans/YYYY/MM/YYYY-MM-DD.md")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by the CLI test
    raise SystemExit(main())
