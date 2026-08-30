# [review:need-review] PHASE-03/89
# summary: the marks of a day read out of the artefacts that carry them — the `<script id="plan-state">` block of a rendered `.html` (with the generated schedule rows recognised as duplicates) and the `.report.md` the exporter writes
"""
Where the marks of a day survived, and how they name the line they belong to.

The `.html` plans are the only record of a tick this system ever kept: the marks
never went into git and never went into the `.md`. Reading them back is the last
chance to keep them, and the reading is done against the **rendered page**, not
against the markdown.

That is the decision worth defending. A key like `t7` means "the eighth row of a
table on the page", and the page is generated: the schedule at the top of the
plan is six rows nobody wrote, and every mark below it is shifted by six. Worse,
`plan_html.py` regenerates the page whenever the `.md` changes while keeping the
old keys, so the mapping from a key to a line is a fact about the file on disk
and not about the current markdown. Recomputing it from the `.md` would land the
marks of 28 August one row off, silently. So the html is parsed for what each key
pointed at, and the line is then found by **what it says**.

Two consequences are visible in the output.

**The schedule rows are aliases, not lines.** They are generated from the very
windows they list, so a tick on one is a tick on the task or the hard point it
came from. It is honoured only when that item carries no tick of its own —
otherwise the item's own answer wins and the disagreement is reported instead of
being resolved by a coin toss. 28 August has such a pair: the schedule copy of
«12:00 Ногти» says failed and the row itself says done.

**A mark that matches nothing is never dropped.** It comes back as
`unmatched`, is named in the report with its key and file, and the file it came
from is stored whole in `import_source.raw`.

The exporter's `.report.md` is read by the same rules — it names an item by its
text too. The `.report.md` that `plan_server.py` used to write is a different
document with the same name (it opens `# Отчёт дня`), and it is recognised and
left alone: its lists are derived from the `.html` that sits next to it, so
reading both would import the same ticks twice under two different mappings.
"""

from __future__ import annotations

import html as html_module
import json
import re
from dataclasses import dataclass, field
from datetime import time

from app.imports.md_parser import match_key

__all__ = [
    "DayReport",
    "KeyRow",
    "PlanState",
    "ReportedMark",
    "StateMark",
    "is_exported_report",
    "read_day_report",
    "read_plan_state",
]

# What the browser stored against a key. `""` is "no mark" and is dropped on
# read; the third state of the cycle is absence, exactly as in `#88`.
STATE_BY_GLYPH: dict[str, str] = {"done": "done", "fail": "failed"}

# The key the notebook of the day lives under, alongside the marks of the lines.
NOTEBOOK_KEY = "day"

# The families of key `initPlan()` hands out, and the element each one counts.
FORM_LIST_ITEM = "li"
FORM_TABLE_ROW = "tr"
FORM_TASK_HEADING = "h3"
FORM_TASK_LINK = "link"

_MAIN_RE = re.compile(r"<main>(.*?)</main>", re.DOTALL)
_STATE_RE = re.compile(
    r'<script id="plan-state"[^>]*>(?P<body>.*?)</script>', re.DOTALL
)
_SCHEDULE_RE = re.compile(
    r'<section class="wide schedule">(?P<body>.*?)</section>', re.DOTALL
)
_ROW_RE = re.compile(r"<tr[^>]*>(?P<body>.*?)</tr>", re.DOTALL)
_CELL_RE = re.compile(r"<td[^>]*>(?P<body>.*?)</td>", re.DOTALL)
_LIST_ITEM_RE = re.compile(r"<li[^>]*>(?P<body>.*?)</li>", re.DOTALL)
_TASK_RE = re.compile(r'<h3 class="task">(?P<body>.*?)</h3>', re.DOTALL)
# Added by the renderer, not written by anyone: the window chip in a task
# heading, and the "free until then" / "clash" notes in a schedule row.
_CHIP_RE = re.compile(r'<span class="when">.*?</span>', re.DOTALL)
_GAP_RE = re.compile(r'<span class="(?:gap|warn)">.*?</span>', re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")

# The three columns of the generated schedule: when, how long, what.
_SCHEDULE_WHAT_COLUMN = 2

# `# Как прошло — 2026-08-28 (пт)` opens a report written by
# `app.exports.personal_os`; `# Отчёт дня 2026-08-28` opens the one
# `plan_server.py` wrote.
EXPORTED_REPORT_RE = re.compile(r"^#\s+Как прошло\s+[—–-]\s+(\d{4}-\d{2}-\d{2})")
OPENED_RE = re.compile(r"^-\s+Открыт\s+::\s+(?P<value>.+)$")
REPORT_ROW_RE = re.compile(r"^\|(?P<cells>.+)\|\s*$")
TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")

# The words `app.exports.personal_os` writes a state as.
STATE_BY_TITLE_RU: dict[str, str] = {
    "сделано": "done",
    "не сделано": "failed",
    "снято": "skipped",
}


def _strip_tags(fragment: str) -> str:
    return html_module.unescape(_TAG_RE.sub("", fragment))


@dataclass(frozen=True)
class StateMark:
    """One entry of the `plan-state` block: a state, a note, or both."""

    key: str
    state: str | None
    note: str | None

    @property
    def is_empty(self) -> bool:
        return self.state is None and not (self.note or "").strip()


@dataclass(frozen=True)
class KeyRow:
    """
    What one key of the `plan-state` block pointed at on the page.

    `alias_of` is set for the rows of the generated schedule: the signature of
    the line the row was built from, rather than a line of its own.
    """

    key: str
    form: str
    signature: str
    alias_of: str | None = None


@dataclass(frozen=True)
class PlanState:
    """The marks of one rendered plan, and what each key pointed at."""

    keys: list[KeyRow] = field(default_factory=list)
    marks: dict[str, StateMark] = field(default_factory=dict)
    notebook: str | None = None

    def key_row(self, key: str) -> KeyRow | None:
        for row in self.keys:
            if row.key == key:
                return row
        return None


@dataclass(frozen=True)
class ReportedMark:
    """One row of the `## Отметки` table of an exported report."""

    signature: str
    state: str
    note: str | None


@dataclass(frozen=True)
class DayReport:
    """An exported `.report.md`, read back."""

    opened_at_local: time | None
    marks: list[ReportedMark] = field(default_factory=list)
    notebook: str | None = None


def read_plan_state(page: str) -> PlanState | None:
    """
    The marks of a rendered plan, or None when the page carries none.

    A page without the `<script id="plan-state">` block was never opened with
    the server running — 22 and 31 August are two such — and that is a fact
    about the day, not a parse failure.
    """
    stored = _read_state_block(page)
    if stored is None:
        return None

    marks: dict[str, StateMark] = {}
    notebook: str | None = None
    for key, value in stored.items():
        if not isinstance(value, dict):
            continue
        state = STATE_BY_GLYPH.get(str(value.get("s") or ""))
        note = value.get("n")
        note_text = str(note) if note is not None else None
        if key == NOTEBOOK_KEY:
            notebook = (note_text or "").strip() or None
            continue
        mark = StateMark(key=key, state=state, note=note_text)
        if mark.is_empty:
            continue
        marks[key] = mark

    return PlanState(keys=_read_keys(page), marks=marks, notebook=notebook)


def _read_state_block(page: str) -> dict[str, object] | None:
    """
    The JSON of the last `plan-state` block, or None.

    `strict=False` because the notebook is free text: a person pressing Enter in
    the textarea puts a raw newline inside a JSON string, and every one of the
    surviving files has one.
    """
    bodies = [
        match.group("body")
        for match in _STATE_RE.finditer(page)
        if match.group("body").strip().startswith("{")
    ]
    if not bodies:
        return None
    parsed = json.loads(bodies[-1], strict=False)
    if not isinstance(parsed, dict):
        return None
    return parsed


def _read_keys(page: str) -> list[KeyRow]:
    """
    Every key `initPlan()` would hand out, in the order it hands them out.

    The order is the DOM order of `querySelectorAll`, which is document order —
    which is why the whole of `<main>` is walked once per family rather than
    section by section.
    """
    main = _MAIN_RE.search(page)
    body = main.group(1) if main else page

    rows: list[KeyRow] = []
    for index, item in enumerate(_LIST_ITEM_RE.finditer(body)):
        rows.append(
            KeyRow(
                key=f"i{index}",
                form=FORM_LIST_ITEM,
                signature=match_key(_strip_tags(item.group("body"))),
            )
        )

    schedule = _schedule_aliases(body)
    # Body rows only, and filtered *before* they are numbered: `initPlan()`
    # counts `table tbody tr`, so a `<thead>` row takes no key and must not
    # advance the numbering either.
    for index, fragment in enumerate(_body_rows(body)):
        alias = schedule[index] if index < len(schedule) else None
        rows.append(
            KeyRow(
                key=f"t{index}",
                form=FORM_TABLE_ROW,
                signature=match_key(_strip_tags(fragment)),
                alias_of=alias,
            )
        )

    for index, task in enumerate(_TASK_RE.finditer(body)):
        signature = match_key(_strip_tags(_CHIP_RE.sub("", task.group("body"))))
        rows.append(
            KeyRow(key=f"w{index}", form=FORM_TASK_HEADING, signature=signature)
        )
        # The ClickUp slot under every task heading shares the task's index and
        # keeps a url rather than a state.
        rows.append(KeyRow(key=f"u{index}", form=FORM_TASK_LINK, signature=signature))

    return rows


def _schedule_aliases(body: str) -> list[str]:
    """
    The line each row of the generated schedule was built from.

    Returned positionally: the schedule is the first section of the page, so its
    rows are the first `t` keys, and everything after them is a table somebody
    actually wrote.
    """
    section = _SCHEDULE_RE.search(body)
    if section is None:
        return []
    aliases: list[str] = []
    for fragment in _body_rows(section.group("body")):
        cells = [cell.group("body") for cell in _CELL_RE.finditer(fragment)]
        if len(cells) <= _SCHEDULE_WHAT_COLUMN:
            continue
        what = _GAP_RE.sub("", cells[_SCHEDULE_WHAT_COLUMN])
        aliases.append(match_key(_strip_tags(what)))
    return aliases


def _body_rows(fragment: str) -> list[str]:
    """Every `<tr>` of `fragment` that holds cells rather than column names."""
    return [
        row.group("body")
        for row in _ROW_RE.finditer(fragment)
        if "<td" in row.group("body")
    ]


def is_exported_report(text: str) -> bool:
    """Whether a `.report.md` is one `app.exports.personal_os` wrote."""
    first = text.lstrip().splitlines()[0] if text.strip() else ""
    return EXPORTED_REPORT_RE.match(first) is not None


def read_day_report(text: str) -> DayReport | None:
    """
    An exported `.report.md` read back into marks, a notebook and an open time.

    Returns None for any other document with that name, including the report
    `plan_server.py` wrote: its lists are derived from the `.html` beside it, and
    importing both would tick the same lines twice under two mappings.
    """
    if not is_exported_report(text):
        return None

    opened: time | None = None
    marks: list[ReportedMark] = []
    notebook_lines: list[str] = []
    in_notebook = False

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_notebook = stripped[3:].strip().lower().startswith("блокнот")
            continue
        if in_notebook:
            notebook_lines.append(line)
            continue
        opened_match = OPENED_RE.match(stripped)
        if opened_match is not None:
            opened = _read_time(opened_match.group("value").strip())
            continue
        row = REPORT_ROW_RE.match(stripped)
        if row is None:
            continue
        cells = [cell.strip() for cell in row.group("cells").split("|")]
        reported = _read_report_row(cells)
        if reported is not None:
            marks.append(reported)

    notebook = "\n".join(notebook_lines).strip() or None
    return DayReport(opened_at_local=opened, marks=marks, notebook=notebook)


def _read_time(value: str) -> time | None:
    match = TIME_RE.match(value)
    if match is None:
        return None
    hours, minutes = int(match.group(1)), int(match.group(2))
    try:
        return time(hours, minutes)
    except ValueError:
        return None


def _read_report_row(cells: list[str]) -> ReportedMark | None:
    """One `| Пункт | Итог | Как прошло |` row, or None for a header."""
    expected_columns = 3
    if len(cells) < expected_columns:
        return None
    state = STATE_BY_TITLE_RU.get(cells[1].lower())
    if state is None:
        return None
    return ReportedMark(
        signature=match_key(cells[0].replace("\\|", "|")),
        state=state,
        note=cells[2].replace("\\|", "|").strip() or None,
    )
