# [review:need-review] PHASE-03/93
# summary: `goal.md` read into the four goal tables — `## Уровень N` blocks with their `⚠ подтверди` questions, the milestone table with «Открывается чем» unrolled into edges, and the numbered list of the quarter normalised from «Q3 2026» to `2026-Q3`; every write is an upsert that leaves `milestone.status` and `milestone.done_on` alone
"""
`goal.md` of `personal-os` as rows.

A module of its own rather than a branch of `app.imports.personal_os`: that one
is a thousand lines about days, plans and marks, and this file is read by
completely different rules — six prose blocks, one table and one numbered list.
The CLI stays single, as the ticket asks: `import_root` calls in here.

**Импорт не угадывает статус милстона.** Whether M2 is done is a fact a person
establishes, and `goal.md` records no such thing. So an insert sets `open` and a
second run rewrites only the text columns: a milestone marked done by hand
survives a re-read, and idempotence is not bought by overwriting.

**Цели квартала не перезаводятся, а обновляются на месте.** `quarter_goal.id` is
what `plan_item.quarter_goal_id` points at, so deleting five rows and inserting
five equal ones would hand every goal a new id and break the link a day was
planned with. The key of an upsert is `(quarter, ord)` — the pair the file
itself names.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.day.plan_validate import to_plain
from app.models.goal import GoalLevel, Milestone, MilestoneDep, QuarterGoal

__all__ = ["ParsedGoals", "ParsedLevel", "import_goals", "parse_goals"]

# `## Уровень 3 — быт: милстоны` — the number is the key of the row, the tail is
# its title.
LEVEL_RE = re.compile(r"^##\s+Уровень\s+(\d)\s*(?:[—–-]\s*(.*))?$")

# `` `⚠ подтверди: какой из двух главный` `` — everything the author marked as
# guessed rather than told. Kept as questions: folding them into `body_md` is
# exactly what the mark in the file exists to prevent.
OPEN_QUESTION_RE = re.compile(r"`(⚠\s*подтверди[^`]*)`")

# A row of the milestone table: `| M1 | **Переезд** | переехал | сейчас | … |`.
MILESTONE_CODE_RE = re.compile(r"^M\d+$")

# Milestone codes inside «Открывается чем»: `M9 + M8`, `M2 (без ипотеки)`. The
# cell is prose, and «ничем, это первый шаг» names none.
CODE_IN_TEXT_RE = re.compile(r"\bM\d+\b")

# `**Q3 2026 (июль-сентябрь), осталось шесть недель:**` — the heading of the
# quarter's list.
QUARTER_RE = re.compile(r"\bQ(\d)\s+(\d{4})\b")

# `1. **Денежный контур …**` — one goal of the quarter.
QUARTER_ITEM_RE = re.compile(r"^(\d+)\.\s+(.*)$")

# `**M1 — переезд.**` — a goal of the quarter that is also a milestone.
LEADING_CODE_RE = re.compile(r"^\**\s*(M\d+)\b")

# A cell holding nothing: M9 has no criterion of being done and the file says so
# with a dash.
EMPTY_CELLS = frozenset({"", "—", "–", "-"})

LEVEL_MILESTONES = 3
LEVEL_QUARTER = 4


@dataclass
class ParsedLevel:
    """One `## Уровень N` block, with its unconfirmed lines kept apart."""

    level: int
    title: str
    body_md: str
    open_questions: list[str]


@dataclass
class ParsedMilestone:
    """One row of the milestone table, with «Открывается чем» already unrolled."""

    code: str
    title: str
    done_criterion: str | None
    when_text: str | None
    ord: int
    depends_on: list[str] = field(default_factory=list)


@dataclass
class ParsedQuarterGoal:
    """One of the five numbered goals of a quarter."""

    quarter: str
    ord: int
    text_md: str
    milestone_code: str | None


@dataclass
class ParsedGoals:
    """`goal.md` as the four tables see it."""

    levels: list[ParsedLevel] = field(default_factory=list)
    milestones: list[ParsedMilestone] = field(default_factory=list)
    quarter_goals: list[ParsedQuarterGoal] = field(default_factory=list)


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _value(cell: str) -> str | None:
    """A table cell as text, or None when the file wrote it as empty."""
    plain = to_plain(cell).strip()
    return None if plain in EMPTY_CELLS else plain


def _milestones(body: str) -> list[ParsedMilestone]:
    """
    The milestone table of «Уровень 3», in the order it is written.

    Rows are recognised by their first cell being a code — the header, the
    `|---|` separator and any other table in the block are skipped by the same
    test rather than by counting lines.
    """
    found: list[ParsedMilestone] = []
    for line in body.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = _cells(line)
        if len(cells) < 5 or not MILESTONE_CODE_RE.match(cells[0]):
            continue
        title = _value(cells[1])
        found.append(
            ParsedMilestone(
                code=cells[0],
                title=title if title is not None else cells[0],
                done_criterion=_value(cells[2]),
                when_text=_value(cells[3]),
                ord=len(found) + 1,
                depends_on=CODE_IN_TEXT_RE.findall(cells[4]),
            )
        )
    # «Открывается чем» is prose, and prose names codes the graph cannot carry:
    # a milestone that mentions itself would be an edge `M5 -> M5`, and a number
    # taken from a sentence rather than from the table (`M11`) has no row to
    # point at and would fail the foreign key as a raw `IntegrityError`. Both
    # are dropped here, where the whole table is in hand and «which codes exist»
    # is answerable.
    known = {one.code for one in found}
    for one in found:
        one.depends_on = [
            code for code in one.depends_on if code != one.code and code in known
        ]
    return found


def _quarter_goals(body: str) -> list[ParsedQuarterGoal]:
    """
    The numbered list of «Уровень 4», under the heading that names the quarter.

    The quarter is read from the heading above the list rather than from the
    calendar: the file is the record of which quarter these five goals belong
    to, and importing it in October must not relabel them.
    """
    quarter: str | None = None
    found: list[ParsedQuarterGoal] = []
    for line in body.splitlines():
        stripped = line.strip()
        item = QUARTER_ITEM_RE.match(stripped)
        if item is None:
            match = QUARTER_RE.search(stripped)
            if match is not None:
                quarter = f"{match.group(2)}-Q{match.group(1)}"
            continue
        if quarter is None:
            continue
        text_md = item.group(2).strip()
        code = LEADING_CODE_RE.match(text_md)
        found.append(
            ParsedQuarterGoal(
                quarter=quarter,
                ord=int(item.group(1)),
                text_md=text_md,
                milestone_code=code.group(1) if code else None,
            )
        )
    return found


def parse_goals(text: str) -> ParsedGoals:
    """`goal.md` as levels, milestones and the goals of the quarter."""
    parsed = ParsedGoals()
    heading: re.Match[str] | None = None
    body: list[str] = []

    def close() -> None:
        if heading is None:
            return
        block = "\n".join(body).strip()
        level = int(heading.group(1))
        parsed.levels.append(
            ParsedLevel(
                level=level,
                title=(heading.group(2) or "").strip(),
                body_md=block,
                open_questions=[
                    question.strip() for question in OPEN_QUESTION_RE.findall(block)
                ],
            )
        )
        if level == LEVEL_MILESTONES:
            parsed.milestones = _milestones(block)
        if level == LEVEL_QUARTER:
            parsed.quarter_goals = _quarter_goals(block)

    for line in text.splitlines():
        match = LEVEL_RE.match(line.strip())
        if match is None:
            body.append(line)
            continue
        close()
        heading = match
        body = []
    close()
    return parsed


async def import_goals(db: AsyncSession, text: str) -> ParsedGoals:
    """
    Read `text` as `goal.md` and put what it says into the four goal tables.

    Every write is an upsert keyed by what the file itself names — the level
    number, the milestone code, the pair `(quarter, ord)`. Nothing is deleted
    and re-created, because `quarter_goal.id` is what a planned day points at.
    """
    parsed = parse_goals(text)

    for level in parsed.levels:
        statement = pg_insert(GoalLevel).values(
            level=level.level,
            title=level.title,
            body_md=level.body_md,
            open_questions=level.open_questions,
        )
        await db.execute(
            statement.on_conflict_do_update(
                index_elements=[GoalLevel.level],
                set_={
                    "title": statement.excluded.title,
                    "body_md": statement.excluded.body_md,
                    "open_questions": statement.excluded.open_questions,
                },
            )
        )

    for milestone in parsed.milestones:
        statement = pg_insert(Milestone).values(
            code=milestone.code,
            title=milestone.title,
            done_criterion=milestone.done_criterion,
            when_text=milestone.when_text,
            ord=milestone.ord,
        )
        # `status` and `done_on` are deliberately absent from `set_`: the file
        # does not record them, and a person does.
        await db.execute(
            statement.on_conflict_do_update(
                index_elements=[Milestone.code],
                set_={
                    "title": statement.excluded.title,
                    "done_criterion": statement.excluded.done_criterion,
                    "when_text": statement.excluded.when_text,
                    "ord": statement.excluded.ord,
                },
            )
        )
    await db.flush()

    await _replace_dependencies(db, parsed.milestones)

    for goal in parsed.quarter_goals:
        statement = pg_insert(QuarterGoal).values(
            quarter=goal.quarter,
            ord=goal.ord,
            text_md=goal.text_md,
            milestone_code=goal.milestone_code,
        )
        await db.execute(
            statement.on_conflict_do_update(
                index_elements=[QuarterGoal.quarter, QuarterGoal.ord],
                set_={
                    "text_md": statement.excluded.text_md,
                    "milestone_code": statement.excluded.milestone_code,
                },
            )
        )
    await db.flush()
    return parsed


async def _replace_dependencies(
    db: AsyncSession, milestones: list[ParsedMilestone]
) -> None:
    """
    The graph as the file draws it, adding what is missing and dropping the rest.

    A difference rather than a delete-and-insert: an edge the file still names is
    left alone, which is what makes a second run touch no row.
    """
    wanted = {
        (milestone.code, depends_on)
        for milestone in milestones
        for depends_on in milestone.depends_on
    }
    result = await db.execute(
        select(MilestoneDep.milestone_code, MilestoneDep.depends_on_code)
    )
    stored = {(code, depends_on) for code, depends_on in result}

    for code, depends_on in sorted(wanted - stored):
        db.add(MilestoneDep(milestone_code=code, depends_on_code=depends_on))
    for code, depends_on in stored - wanted:
        edge = await db.get(MilestoneDep, (code, depends_on))
        if edge is not None:
            await db.delete(edge)
    await db.flush()
