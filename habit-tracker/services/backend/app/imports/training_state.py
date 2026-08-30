# [review:need-review] PHASE-03/92
# summary: reads `training/state.md` — the dynamic frontmatter keys `planned_<date>`/`done_<date>`/`skipped_<date>` unrolled into rows of `training_day`, the `last_*` dates stamped onto the days they name so the recompute reproduces them, the dated paragraphs of the notes attached to their dates, plus the open complaints, the personal records and the authored progression
"""
`training/state.md`, развёрнутый в строки.

Файл держал таблицу свёрнутой во frontmatter: `planned_2026-08-30`,
`done_2026-08-30`, `skipped_2026-08-14`. Такую таблицу нельзя запросить, нельзя
посчитать и легко испортить одной опечаткой в дате — «pull не подтверждён с
17.08» приходилось считать человеку, читая прозу. Здесь каждый ключ становится
строкой `training_day`, каждая датированная заметка — прозой той же строки.

**Даты `last_*` не переносятся в состояние, а проставляются на дни.**
`training_state` производный: записать в него `last_heavy_pull: 2026-08-17`
означало бы вернуть ровно ту болезнь, от которой уходим — снимок, которому надо
верить на слово. Вместо этого день 17 августа получает паттерн `pull` в
`heavy_patterns`, и пересчёт выводит ту же дату из строк. То же с ногами, бегом,
улицей и кардио.

**`week_sets` кладётся на самый поздний день файла.** Счётчик недели в файле —
сумма с понедельника той недели, когда файл писался; сумма по строкам
воспроизводит её ровно тогда, когда пересчёт делается на этот же день. Дата
последней записи и есть тот день.

**`skipped_days` из файла игнорируется намеренно.** В живом файле стоит `0` при
трёх ключах `skipped_*` — это и есть цена свёрнутой в YAML таблицы. Значение
выводится из строк, а не переносится.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import day as day_crud
from app.crud import training as training_crud
from app.models.training import (
    COMPLAINT_OPEN,
    PATTERN_CARDIO,
    PATTERN_LEGS,
    PATTERN_PULL,
    PATTERN_PUSH,
    PATTERN_RUN,
    BodyComplaint,
    PersonalRecord,
)

__all__ = [
    "TRAINING_STATE_FILE",
    "ParsedComplaint",
    "ParsedRecord",
    "ParsedTrainingDay",
    "ParsedTrainingState",
    "TrainingImportReport",
    "import_training_state",
    "parse_training_state",
]

# Where the file lives inside `personal-os`.
TRAINING_STATE_FILE = "training/state.md"

# `planned_2026-08-30`, `done_2026-08-30`, `skipped_2026-08-14` — the folded
# table. The date is the key's tail, and a key whose tail is not a date is
# reported rather than guessed at.
DATED_KEY_RE = re.compile(r"^(planned|done|skipped)_(\d{4}-\d{2}-\d{2})$")

# «**2026-08-12.** Ноги+кор, 36 минут…» — a paragraph of the notes about one
# date. A heading naming a range («**2026-08-15 — 16.08.**») is attached to the
# first date it names; there is nothing better to do with prose about two days.
NOTE_HEAD_RE = re.compile(r"^\*\*(\d{4}-\d{2}-\d{2})", re.MULTILINE)

# Which `last_*` key stamps which pattern, and whether it stamps it as heavy.
# Data rather than an if-chain: adding a seventh pattern is a line here.
LAST_KEYS: tuple[tuple[str, str, bool], ...] = (
    ("last_heavy_pull", PATTERN_PULL, True),
    ("last_heavy_push", PATTERN_PUSH, True),
    ("last_legs", PATTERN_LEGS, False),
    ("last_run", PATTERN_RUN, False),
    ("last_cardio", PATTERN_CARDIO, False),
)

FRONTMATTER_FENCE = "---"


@dataclass
class ParsedTrainingDay:
    """One date of the file, gathered from every key that names it."""

    day_date: date
    planned_md: str | None = None
    done_md: str | None = None
    skipped: bool = False
    patterns: set[str] = field(default_factory=set)
    heavy_patterns: set[str] = field(default_factory=set)
    outdoor_done: bool | None = None
    near_failure: bool = False
    note_md: str | None = None
    sets: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedComplaint:
    """One row of `complaints:` — a symptom, never a diagnosis."""

    opened_on: date
    area: str
    context: str | None
    severity: str | None
    status: str


@dataclass(frozen=True)
class ParsedRecord:
    """One entry of `prs:`."""

    exercise: str
    variant: str | None
    sets: str | None
    best_plain: int | None
    achieved_on: date
    target: str | None


@dataclass
class ParsedTrainingState:
    """Everything `training/state.md` says, keyed the way rows are keyed."""

    days: dict[date, ParsedTrainingDay] = field(default_factory=dict)
    complaints: list[ParsedComplaint] = field(default_factory=list)
    records: list[ParsedRecord] = field(default_factory=list)
    progression: dict[str, str] = field(default_factory=dict)
    unread: list[str] = field(default_factory=list)

    def day(self, on: date) -> ParsedTrainingDay:
        """The day `on`, created empty the first time something names it."""
        if on not in self.days:
            self.days[on] = ParsedTrainingDay(day_date=on)
        return self.days[on]


@dataclass
class TrainingImportReport:
    """What one run of the training import wrote."""

    days: int = 0
    complaints: int = 0
    records: int = 0
    progression: bool = False
    unread: list[str] = field(default_factory=list)

    def as_lines(self) -> list[str]:
        return [
            f"training/state.md: дней {self.days}, жалоб {self.complaints}, "
            f"рекордов {self.records}",
            f"прогрессия: {'прочитана' if self.progression else 'нет'}",
            f"непрочитанного: {len(self.unread)}",
        ]


def _frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """
    The YAML head of the file and everything after it.

    A file with no frontmatter is not an error: the answer is an empty mapping
    and the whole text as the body, so a half-written file imports its notes
    instead of failing outright.
    """
    if not text.startswith(FRONTMATTER_FENCE):
        return {}, text
    parts = text.split(f"\n{FRONTMATTER_FENCE}\n", 1)
    if len(parts) != 2:
        return {}, text
    head = parts[0][len(FRONTMATTER_FENCE) :]
    loaded = yaml.safe_load(head)
    return (loaded if isinstance(loaded, dict) else {}), parts[1]


def _as_date(value: Any) -> date | None:
    """A YAML scalar as a date, or None when it is not one."""
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _read_dated_keys(head: Mapping[str, Any], parsed: ParsedTrainingState) -> None:
    """`planned_<date>` / `done_<date>` / `skipped_<date>` into their days."""
    for key, value in head.items():
        match = DATED_KEY_RE.match(str(key))
        if match is None:
            continue
        on = date.fromisoformat(match.group(2))
        day = parsed.day(on)
        if match.group(1) == "planned":
            day.planned_md = str(value)
        elif match.group(1) == "done":
            day.done_md = str(value)
        else:
            day.skipped = bool(value)


def _read_last_keys(head: Mapping[str, Any], parsed: ParsedTrainingState) -> None:
    """
    The `last_*` dates, stamped onto the days they name.

    This is what keeps the state derived. Writing them into `training_state`
    would restore the very thing this ticket removes: a snapshot nothing can
    check.
    """
    for key, pattern, heavy in LAST_KEYS:
        on = _as_date(head.get(key))
        if on is None:
            continue
        day = parsed.day(on)
        day.patterns.add(pattern)
        if heavy:
            day.heavy_patterns.add(pattern)

    outdoor = _as_date(head.get("last_outdoor"))
    if outdoor is not None:
        parsed.day(outdoor).outdoor_done = True

    for value in head.get("near_failure_days") or []:
        on = _as_date(value)
        if on is None:
            parsed.unread.append(f"near_failure_days: не дата — {value!r}")
            continue
        parsed.day(on).near_failure = True


def _read_week_sets(head: Mapping[str, Any], parsed: ParsedTrainingState) -> None:
    """
    The week counter, put on the latest date the file names.

    The sum over rows then reproduces it exactly for a recompute made on that
    date, which is what «объём недели совпадает с тем, что было в файле» means
    once the counter stops being a number somebody maintained by hand.
    """
    week_sets = head.get("week_sets")
    if not isinstance(week_sets, dict) or not parsed.days:
        return
    latest = max(parsed.days)
    parsed.day(latest).sets = {
        str(key): int(value)
        for key, value in week_sets.items()
        if isinstance(value, int)
    }


def _read_complaints(head: Mapping[str, Any], parsed: ParsedTrainingState) -> None:
    """`complaints:` — the symptoms that gate a suggestion."""
    for entry in head.get("complaints") or []:
        if not isinstance(entry, dict):
            parsed.unread.append(f"complaints: не запись — {entry!r}")
            continue
        opened = _as_date(entry.get("date"))
        area = entry.get("area")
        if opened is None or not area:
            parsed.unread.append(f"complaints: нет даты или области — {entry!r}")
            continue
        parsed.complaints.append(
            ParsedComplaint(
                opened_on=opened,
                area=str(area),
                context=_text_or_none(entry.get("context")),
                severity=_text_or_none(entry.get("severity")),
                status=str(entry.get("status") or COMPLAINT_OPEN),
            )
        )


def _read_records(head: Mapping[str, Any], parsed: ParsedTrainingState) -> None:
    """`prs:` — one record per exercise, with the target beyond it."""
    entries = head.get("prs")
    if not isinstance(entries, dict):
        return
    for exercise, entry in entries.items():
        if not isinstance(entry, dict):
            parsed.unread.append(f"prs.{exercise}: не запись — {entry!r}")
            continue
        achieved = _as_date(entry.get("date"))
        if achieved is None:
            parsed.unread.append(f"prs.{exercise}: нет даты достижения")
            continue
        best = entry.get("best_plain", entry.get("best"))
        parsed.records.append(
            ParsedRecord(
                exercise=str(exercise),
                variant=_text_or_none(entry.get("variant")),
                sets=_text_or_none(entry.get("sets")),
                best_plain=int(best) if isinstance(best, int) else None,
                achieved_on=achieved,
                target=_text_or_none(entry.get("target")),
            )
        )


def _read_progression(head: Mapping[str, Any], parsed: ParsedTrainingState) -> None:
    """`progression_stage:` — the one authored part of the state."""
    stage = head.get("progression_stage")
    if isinstance(stage, dict):
        parsed.progression = {str(key): str(value) for key, value in stage.items()}


def _read_notes(body: str, parsed: ParsedTrainingState) -> None:
    """
    The dated paragraphs of `## Заметки`, attached to the dates they head.

    Prose about *why* a day went the way it did — «первый подход до отказа съел
    остальные три». Nothing derives it, and nothing else records it.
    """
    heads = list(NOTE_HEAD_RE.finditer(body))
    for position, match in enumerate(heads):
        end = heads[position + 1].start() if position + 1 < len(heads) else len(body)
        on = date.fromisoformat(match.group(1))
        parsed.day(on).note_md = body[match.start() : end].strip()


def _text_or_none(value: Any) -> str | None:
    """A YAML scalar as text, with an absent value staying absent."""
    return None if value is None else str(value)


def parse_training_state(text: str) -> ParsedTrainingState:
    """
    Read the whole file: frontmatter into rows, notes into the days they name.

    Pure — takes the text, returns values, touches nothing. The parse is the
    part worth testing against the live file, and it must not need a database
    to be tested.
    """
    head, body = _frontmatter(text)
    parsed = ParsedTrainingState()
    _read_dated_keys(head, parsed)
    _read_last_keys(head, parsed)
    _read_complaints(head, parsed)
    _read_records(head, parsed)
    _read_progression(head, parsed)
    _read_notes(body, parsed)
    # After the notes, so that a date mentioned only in prose can still be the
    # latest one the file knows.
    _read_week_sets(head, parsed)
    return parsed


async def _known_complaints(db: AsyncSession) -> set[tuple[date, str]]:
    """The complaints already stored, by the pair that identifies one."""
    result = await db.execute(select(BodyComplaint.opened_on, BodyComplaint.area))
    return {(row.opened_on, row.area) for row in result}


async def _known_records(db: AsyncSession) -> set[tuple[str, date]]:
    """The records already stored, by exercise and date."""
    result = await db.execute(
        select(PersonalRecord.exercise, PersonalRecord.achieved_on)
    )
    return {(row.exercise, row.achieved_on) for row in result}


async def import_training_state(db: AsyncSession, text: str) -> TrainingImportReport:
    """
    Write everything `training/state.md` says, and nothing twice.

    Идемпотентен: дни переписываются на месте по первичному ключу даты, жалоба
    узнаётся по паре «дата + область», рекорд — по паре «упражнение + дата». Так
    второй прогон не удваивает ни одной жалобы, что для таблицы, куда пишет и
    файл, и человек, важнее скорости.
    """
    parsed = parse_training_state(text)
    report = TrainingImportReport(unread=list(parsed.unread))

    for on in sorted(parsed.days):
        day = parsed.days[on]
        # The FK of `training_day` points at `day`; a date the calendar has
        # never seen has to exist before its training can.
        await day_crud.ensure_day(db, on)
        await training_crud.upsert_training_day(
            db,
            on,
            patterns=sorted(day.patterns),
            heavy_patterns=sorted(day.heavy_patterns),
            planned_md=day.planned_md,
            done_md=day.done_md,
            skipped=day.skipped,
            outdoor_done=day.outdoor_done,
            near_failure=day.near_failure,
            note_md=day.note_md,
            sets=day.sets,
        )
        report.days += 1

    known_complaints = await _known_complaints(db)
    for complaint in parsed.complaints:
        if (complaint.opened_on, complaint.area) in known_complaints:
            continue
        stored = await training_crud.create_complaint(
            db,
            opened_on=complaint.opened_on,
            area=complaint.area,
            context=complaint.context,
            severity=complaint.severity,
        )
        stored.status = complaint.status
        report.complaints += 1

    known_records = await _known_records(db)
    for record in parsed.records:
        if (record.exercise, record.achieved_on) in known_records:
            continue
        await training_crud.create_record(
            db,
            exercise=record.exercise,
            variant=record.variant,
            sets=record.sets,
            best_plain=record.best_plain,
            achieved_on=record.achieved_on,
            target=record.target,
        )
        report.records += 1

    if parsed.progression:
        await training_crud.set_progression(db, parsed.progression)
        report.progression = True

    # The snapshot is recomputed as of the latest date the file knows, not as of
    # today: the file's own numbers are the ones a reader compares against, and
    # they were written on that day.
    if parsed.days:
        await training_crud.recompute_state(db, max(parsed.days))

    await db.flush()
    return report


def latest_date(days: Iterable[date]) -> date | None:
    """The last date a parse knows, or None for an empty file."""
    known = list(days)
    return max(known) if known else None
