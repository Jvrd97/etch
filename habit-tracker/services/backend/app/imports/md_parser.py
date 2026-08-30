# [review:need-review] PHASE-03/89
# summary: the `.md` plan of personal-os parsed into sections and items — the grammar `plan_html.py` rendered, plus what the renderer threw away (labels, windows, minimums) and a list of everything the parse did not understand
"""
The markdown a plan of `personal-os` was written in, read as rows.

This is the parser `tools/plan_html.py` was: the same front matter split, the
same window regexp, the same `' :: '` branch, the same reading of the first cell
of a table. What it does differently is keep what the renderer dropped — the
renderer needed a screen, this needs the columns of `plan_item`.

Three decisions here are worth reading before changing a rule.

**Nothing is judged.** The parser produces what the file says; `app.crud.plan`
decides whether that is an acceptable plan. A grammar that also enforced the
canon would refuse exactly the historic days worth keeping — the ones written
before the canon existed.

**A line becomes `kind='task'` only when it is written as one.** In the canon
since 2026-08-28 a task is a `### W1 · …` heading with a window and a criterion.
The `- [ ] [W1] …` lines of the older plans are neither, and calling them tasks
would put the five of 10 August over a bar of four and refuse the whole day.
Such a line stays the bullet it was written as, handle and all, inside its text.

**Every item records the shape it had on the page** (`html_form`): a list item,
a table row, a task heading, or nothing at all. That is what lets
`app.imports.plan_state` put a mark left in the `.html` back on the line it was
made against — by what the line says rather than by where it sat.

What the parse does not understand is not guessed at: `<details>` blocks, html
comments and a heading naming the wrong date land in `ParsedPlan.unparsed`, and
the whole file is kept in `import_source.raw` regardless.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.day.plan_validate import to_plain

__all__ = [
    "FIELD_SEPARATOR",
    "ParsedItem",
    "ParsedPlan",
    "ParsedSection",
    "match_key",
    "parse_plan",
    "section_kind",
    "split_front",
    "split_window",
]

# `Подпись :: значение` — the separator that turns a list line into a field of
# the line above it. The spaces are part of it, exactly as in `plan_html.py`:
# `Q3 :: 4` is a field, `a::b` inside a path is not.
FIELD_SEPARATOR = " :: "

# `09:30-11:00, пока ногти` — the time is a prefix, the rest is a comment. Ported
# from `plan_html.WINDOW_RE`, tilde included: the plans write `~09:30` for "about
# half past nine".
WINDOW_PREFIX_RE = re.compile(r"^\s*~?(\d{1,2}):(\d{2})\s*[-–—]\s*~?(\d{1,2}):(\d{2})")

# A duration the plan spelled out after the window (`1.5-2 ч`, `40 мин`). The
# window already says it, and `plan_html.py` dropped it for the same reason.
DURATION_TAIL_RE = re.compile(
    r"^(\d+[.,]?\d*\s*ч(\s*\d+\s*мин)?|\d+\s*мин)[.,;\s—-]*", re.IGNORECASE
)

# `### W1 · Шортлист` — a handle, the middle dot, the text. The handle is what an
# error message names, which is why it is a column and not a prefix of the text.
TASK_HEADING_RE = re.compile(r"^([A-Za-zА-Яа-яЁё][\w\-]*)\s*·\s*(.+)$")

# `# План 2026-08-28 (пт) — день в дороге`: the date and the weekday are
# generated, the tail after the dash is the only part a person wrote.
H1_RE = re.compile(
    r"^План\s+(?P<date>\d{4}-\d{2}-\d{2})\s*(?:\((?P<weekday>[^)]*)\))?"
    r"\s*(?:[—–-]\s*(?P<tail>.+))?$"
)

# `Пятница *в дороге*` — the marked word of the title, rendered as the one
# yellow mark on the page.
TITLE_MARKER_RE = re.compile(r"^(?P<title>.*?)\s*\*(?P<marker>[^*]+)\*\s*$")

LIST_RE = re.compile(r"^(?P<indent>[ \t]*)[-*][ \t]+(?:\[[ xX~]\][ \t]+)?(?P<body>.+)$")
ORDERED_RE = re.compile(
    r"^(?P<indent>[ \t]*)\d+\.[ \t]+(?:\[[ xX~]\][ \t]+)?(?P<body>.+)$"
)
TABLE_SEPARATOR_RE = re.compile(r"^[\s|:-]+$")

# Indent of one nesting level, in spaces — the same two the exporter writes.
INDENT_WIDTH = 2

KIND_BULLET = "bullet"
KIND_STEP = "step"
KIND_TABLE_ROW = "table_row"
KIND_TASK = "task"
KIND_ANCHOR = "anchor"
KIND_MINIMUM = "minimum"

FORM_LIST_ITEM = "li"
FORM_TABLE_ROW = "tr"
FORM_TASK_HEADING = "h3"

# Section titles are prose and change from day to day («Работа — по порядку»,
# «Работа (max 5, по убыванию сложности)»), so the kind is decided by how the
# title starts rather than by the whole string. First match wins, so the more
# specific prefixes come first.
SECTION_KIND_PREFIXES: tuple[tuple[str, str], ...] = (
    ("якор", "anchors"),
    ("тренировк", "training"),
    ("спорт", "training"),
    ("жёстк", "hard_points"),
    ("жестк", "hard_points"),
    ("рабочие часы", "work"),
    ("работ", "work"),
    ("четыре задачи", "work"),
    ("чем занимаемся", "work"),
    ("учёб", "study"),
    ("учеб", "study"),
    ("развивающий", "study"),
    ("свободный вечер", "free"),
    ("свободн", "free"),
    ("вечер", "evening"),
    ("личн", "personal"),
    ("быт", "personal"),
    ("очеред", "queue"),
)

# The labels that earned a column of `plan_item`. Everything else with a
# `Подпись :: значение` shape goes to `extra` whole — that is what makes "ни одна
# подпись не потеряна" a property of the parser rather than of a list somebody
# has to keep up to date.
FIELD_WINDOW = "окно"
FIELD_MINIMUM = "минимум"
COLUMN_BY_LABEL: dict[str, str] = {
    "сделано": "done_criterion",
    "ход": "plan_md",
    "почему": "why_md",
    # Written by `app.exports.personal_os` for a task that names no quarter goal.
    # Read back as the column it came from, so that exporting a day and importing
    # it again does not turn the reason into a nameless `extra` key.
    "вне квартала": "unlinked_reason",
}
EXTERNAL_REF_LABELS: frozenset[str] = frozenset({"clickup"})


@dataclass
class ParsedItem:
    """One line of a plan as the columns of `plan_item` see it."""

    kind: str
    text_md: str
    code: str | None = None
    window: str | None = None
    window_comment: str | None = None
    done_criterion: str | None = None
    why_md: str | None = None
    plan_md: str | None = None
    unlinked_reason: str | None = None
    external_ref: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    children: list[ParsedItem] = field(default_factory=list)

    # What this line looked like on the rendered page, or None when it was not
    # rendered as a markable element at all (a field, a minimum, loose prose).
    html_form: str | None = None

    # The first cell of a table row exactly as written («~09:30», «до 20:00»).
    # Kept apart from `code` because a cell that parsed as a window leaves no
    # code behind, and the rendered row still showed it.
    table_when: str | None = None

    # Filled in by the importer once the `.html` marks have been read.
    legacy_key: str | None = None

    def signature(self) -> str:
        """
        What this line says, as the rendered page would have said it.

        Whitespace is dropped rather than collapsed: stripping the anchor out of
        `Besichtigung ([86cbau6gu](url))` leaves a space where the tag was, and
        two texts that differ only by that space are the same line.
        """
        if self.html_form == FORM_TABLE_ROW:
            source = f"{self.table_when or ''} {self.text_md}"
        elif self.html_form == FORM_TASK_HEADING and self.code:
            source = f"{self.code} · {self.text_md}"
        else:
            source = self.text_md
        return match_key(source)

    def walk(self) -> list[ParsedItem]:
        """This item and everything nested under it, parents first."""
        found = [self]
        for child in self.children:
            found.extend(child.walk())
        return found


@dataclass
class ParsedSection:
    """One `## …` block of a plan."""

    title: str | None
    kind: str
    items: list[ParsedItem] = field(default_factory=list)


@dataclass
class ParsedPlan:
    """A whole `.md` plan, ready to become a `PlanDocument`."""

    title: str | None = None
    title_marker: str | None = None
    lede: str | None = None
    purpose_md: str | None = None
    counters: list[str] = field(default_factory=list)
    condition_tomorrow: str | None = None
    sections: list[ParsedSection] = field(default_factory=list)
    unparsed: list[str] = field(default_factory=list)
    raw_md: str = ""

    def items(self) -> list[ParsedItem]:
        """Every item of every section, in document order, parents first."""
        found: list[ParsedItem] = []
        for section in self.sections:
            for item in section.items:
                found.extend(item.walk())
        return found


def match_key(text: str) -> str:
    """
    The form two renderings of the same line have in common.

    Markdown flattened by the one function that flattens it
    (`plan_validate.to_plain`), then every space removed and the case folded.
    """
    return "".join(to_plain(text).split()).casefold()


def split_front(text: str) -> tuple[dict[str, str], str]:
    """
    The `---` block and the body. Ported from `plan_html.split_front`.

    Deliberately not a YAML load: the front matter of these files is a handful of
    `key: value` lines whose values carry colons, asterisks and semicolons, and a
    real YAML parser would either mangle them or refuse the file.
    """
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 3)
    if end == -1:
        return {}, text
    meta: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" in line and not line.startswith(" "):
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
    return meta, text[end + 5 :]


def section_kind(title: str | None) -> str:
    """Which of `SECTION_KINDS` a section titled `title` is."""
    if not title:
        return "other"
    lowered = title.strip().lower()
    for prefix, kind in SECTION_KIND_PREFIXES:
        if lowered.startswith(prefix):
            return kind
    return "other"


def split_window(value: str) -> tuple[str | None, str | None]:
    """
    `"09:30-11:00, пока ногти. 1.5-2 ч"` to `("09:30-11:00", "пока ногти.")`.

    The window is normalised to the `ЧЧ:ММ-ЧЧ:ММ` the schema takes: the tilde of
    `~09:30` hedges the wall clock rather than naming a different time, and the
    spelled-out duration is dropped because the window already states it.
    """
    match = WINDOW_PREFIX_RE.match(value)
    if match is None:
        return None, value.strip() or None
    start_h, start_m, end_h, end_m = (int(group) for group in match.groups())
    window = f"{start_h:02d}:{start_m:02d}-{end_h:02d}:{end_m:02d}"
    tail = value[match.end() :].lstrip(" ,.;—-")
    tail = DURATION_TAIL_RE.sub("", tail).strip()
    return window, tail or None


def _title_and_marker(raw: str) -> tuple[str | None, str | None]:
    """`Пятница *в дороге*` as its two halves."""
    match = TITLE_MARKER_RE.match(raw.strip())
    if match is None:
        return raw.strip() or None, None
    return match.group("title").strip() or None, match.group("marker").strip() or None


def _depth(indent: str) -> int:
    return len(indent.replace("\t", " " * INDENT_WIDTH)) // INDENT_WIDTH


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


class _Builder:
    """
    The document as it is being read, one line at a time.

    `container` is the `###` heading currently open — a task or a plain
    sub-heading — and `stack[d]` is the last item created at depth `d`. Together
    they answer the only two structural questions the format asks: what a list
    item at depth `d` hangs off, and which item a `Подпись :: значение` belongs
    to.

    `pending` is the field whose value the next indented line would continue. The
    live plans wrap a long `Ход ::` over four lines; without this the tail of the
    sentence would arrive as a separate bullet.
    """

    def __init__(self) -> None:
        self.plan = ParsedPlan()
        self.section: ParsedSection | None = None
        self.container: ParsedItem | None = None
        self.stack: list[ParsedItem | None] = []
        self.paragraph: list[str] = []
        self.table_started = False
        self.pending: Callable[[str], None] | None = None

    # -- structure ---------------------------------------------------------
    def open_section(self, title: str) -> ParsedSection:
        self.flush_paragraph()
        section = ParsedSection(title=title or None, kind=section_kind(title))
        self.plan.sections.append(section)
        self.section = section
        self.container = None
        self.stack = []
        self.table_started = False
        self.pending = None
        return section

    def current_section(self) -> ParsedSection:
        """The section being filled, opening an untitled one if none was named."""
        if self.section is None:
            return self.open_section("")
        return self.section

    def add_item(self, item: ParsedItem, depth: int) -> ParsedItem:
        parent = self.parent_for(depth)
        if parent is None:
            self.current_section().items.append(item)
        else:
            parent.children.append(item)
        # `stack[d]` has to stay the last item *at depth d*, so a level nobody
        # wrote a line at is a hole rather than a shift: an item indented once
        # under a heading must not become the parent of the next one.
        del self.stack[depth:]
        while len(self.stack) < depth:
            self.stack.append(None)
        self.stack.append(item)
        self.pending = _appender(item, "text_md")
        return item

    def nearest(self, depth: int) -> ParsedItem | None:
        """The deepest item at or above `depth` that a line at `depth` hangs off."""
        for level in range(min(depth, len(self.stack)) - 1, -1, -1):
            found = self.stack[level]
            if found is not None:
                return found
        return self.container

    def parent_for(self, depth: int) -> ParsedItem | None:
        """
        What an item at `depth` belongs to, or None for the section itself.

        An unindented line under an open `###` belongs to that heading when the
        heading is a grouping one («### P1 — появилось сегодня» collects the
        lines below it) and to the section when it is a task: a task owns its
        labels and its indented lines, but the next unindented bullet is the
        plan going on, not a step of the task. That is also the only reading
        under which a day exported to `.md` and read back is the day it was.
        """
        if depth > 0:
            return self.nearest(depth)
        if self.container is not None and self.container.kind != KIND_TASK:
            return self.container
        return None

    def field_owner(self, depth: int) -> ParsedItem | None:
        """
        The item a `Подпись :: значение` at `depth` describes.

        An indented label belongs to the line above it. An unindented one belongs
        to the open `###` heading whenever there is one — «Сделано ::» after the
        three numbered steps of a task is still the criterion of the task.
        """
        if depth > 0:
            return self.nearest(depth)
        if self.container is not None:
            return self.container
        return self.stack[-1] if self.stack else None

    # -- content -----------------------------------------------------------
    def flush_paragraph(self) -> None:
        """Loose prose between lists becomes one bullet, not one per line."""
        if not self.paragraph:
            return
        text = " ".join(self.paragraph).strip()
        self.paragraph = []
        if text:
            # Loose prose in a section of anchors is a line of that section like
            # any other: it comes back from the export as a bullet, and reading
            # it as a different kind than its neighbours would make a day
            # exported and re-imported differ from itself.
            self.add_item(
                ParsedItem(kind=_item_kind(self, ordered=False, depth=0), text_md=text),
                depth=0,
            )

    def add_field(self, label: str, value: str, depth: int) -> None:
        owner = self.field_owner(depth)
        key = label.strip().lower()
        self.pending = None

        if key == FIELD_MINIMUM:
            # A minimum is a line with a tick of its own since `#88`, not a
            # sentence inside the task it belongs to.
            item = ParsedItem(kind=KIND_MINIMUM, text_md=value.strip())
            if owner is None:
                self.current_section().items.append(item)
            else:
                owner.children.append(item)
            self.pending = _appender(item, "text_md")
            return

        if owner is None:
            # A label with nothing above it to describe («- P1 :: Пусто» opening
            # a section). It is kept as the line it was written as rather than
            # dropped — but as a line, not as a field of the section.
            line = f"{label}{FIELD_SEPARATOR}{value}".strip()
            self.add_item(ParsedItem(kind=KIND_BULLET, text_md=line), depth=0)
            self.plan.unparsed.append(f"подпись без пункта, сохранена строкой: {line}")
            return

        if key == FIELD_WINDOW:
            window, comment = split_window(value)
            if window is None:
                owner.extra[label.strip()] = value.strip()
                return
            owner.window = window
            owner.window_comment = comment
            return

        column = COLUMN_BY_LABEL.get(key)
        if column is not None:
            setattr(owner, column, value.strip())
            self.pending = _appender(owner, column)
            return

        if key in EXTERNAL_REF_LABELS:
            reference = dict(owner.external_ref or {})
            reference[key] = value.strip()
            owner.external_ref = reference
            return

        owner.extra[label.strip()] = value.strip()
        self.pending = _extra_appender(owner, label.strip())


def _appender(item: ParsedItem, attribute: str) -> Callable[[str], None]:
    """Continue a wrapped value on the attribute it belongs to."""

    def append(text: str) -> None:
        current = getattr(item, attribute)
        setattr(item, attribute, f"{current} {text}".strip() if current else text)

    return append


def _extra_appender(item: ParsedItem, key: str) -> Callable[[str], None]:
    def append(text: str) -> None:
        current = item.extra.get(key)
        item.extra[key] = f"{current} {text}".strip() if current else text

    return append


def _consume_front_matter(builder: _Builder, meta: dict[str, str]) -> None:
    title = meta.get("title")
    if title:
        builder.plan.title, builder.plan.title_marker = _title_and_marker(title)
    builder.plan.lede = meta.get("lede") or None
    builder.plan.purpose_md = meta.get("purpose") or None
    builder.plan.condition_tomorrow = meta.get("condition_tomorrow") or None
    counters = meta.get("counters")
    if counters:
        builder.plan.counters = [
            part.strip() for part in counters.split(";") if part.strip()
        ]


def _item_kind(builder: _Builder, *, ordered: bool, depth: int) -> str:
    if ordered:
        return KIND_STEP
    section = builder.current_section()
    if section.kind == "anchors" and depth == 0 and builder.container is None:
        return KIND_ANCHOR
    return KIND_BULLET


def parse_plan(text: str, on: date) -> ParsedPlan:
    """
    One `.md` plan of `personal-os` as sections and items.

    `on` is the date the file is named after, and it is read rather than
    computed with: the only use is telling a heading that names another date
    from one that does not.
    """
    meta, body = split_front(text)
    builder = _Builder()
    builder.plan.raw_md = text
    _consume_front_matter(builder, meta)

    lines = body.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        index += 1

        if not stripped:
            builder.flush_paragraph()
            builder.table_started = False
            builder.pending = None
            continue

        if stripped.startswith("<!--"):
            builder.plan.unparsed.append(stripped)
            continue

        if stripped.startswith("<details"):
            builder.flush_paragraph()
            block = [stripped]
            while index < len(lines) and "</details>" not in lines[index - 1]:
                block.append(lines[index].rstrip())
                index += 1
            builder.plan.unparsed.append("\n".join(block))
            builder.pending = None
            continue

        if stripped.startswith("# "):
            builder.flush_paragraph()
            _read_h1(builder, stripped[2:].strip(), on)
            continue

        if stripped.startswith("## "):
            builder.open_section(stripped[3:].strip())
            continue

        if stripped.startswith("### "):
            _read_h3(builder, stripped[4:].strip())
            continue

        if stripped.startswith(">"):
            builder.flush_paragraph()
            builder.pending = None
            quote = [stripped.lstrip(">").strip()]
            while index < len(lines) and lines[index].strip().startswith(">"):
                quote.append(lines[index].strip().lstrip(">").strip())
                index += 1
            text_md = " ".join(part for part in quote if part).strip()
            if text_md:
                builder.add_item(ParsedItem(kind=KIND_BULLET, text_md=text_md), depth=0)
            continue

        if stripped.startswith("|"):
            builder.flush_paragraph()
            _read_table_row(builder, stripped)
            continue

        builder.table_started = False
        ordered = ORDERED_RE.match(line)
        match = LIST_RE.match(line) or ordered
        if match is not None:
            builder.flush_paragraph()
            _read_list_line(builder, match, ordered=ordered is not None)
            continue

        if builder.pending is not None and line[:1].isspace():
            builder.pending(stripped)
            continue

        builder.paragraph.append(stripped)

    builder.flush_paragraph()
    return builder.plan


def _read_h1(builder: _Builder, text: str, on: date) -> None:
    """The H1: a generated `План <дата> (дд)` plus, sometimes, a real title."""
    match = H1_RE.match(text)
    if match is None:
        if builder.plan.title is None:
            builder.plan.title = text or None
        return
    tail = match.group("tail")
    if builder.plan.title is None and tail:
        builder.plan.title = tail.strip()
    if match.group("date") != on.isoformat():
        builder.plan.unparsed.append(
            f"# {text} — заголовок называет не ту дату, файл лежит как {on.isoformat()}"
        )


def _read_h3(builder: _Builder, text: str) -> None:
    """
    A `###` heading opens a container: a work task, or a plain sub-heading.

    A sub-heading («### P1 — появилось сегодня») becomes a bullet with the lines
    under it as its children: the grouping it expresses is real, and the schema
    has no third level of section to put it in.
    """
    builder.flush_paragraph()
    builder.stack = []
    builder.table_started = False
    builder.pending = None
    match = TASK_HEADING_RE.match(text)
    if match is None:
        item = ParsedItem(kind=KIND_BULLET, text_md=text)
        builder.current_section().items.append(item)
        builder.container = item
        return
    task = ParsedItem(
        kind=KIND_TASK,
        text_md=match.group(2).strip(),
        code=match.group(1).strip(),
        html_form=FORM_TASK_HEADING,
    )
    builder.current_section().items.append(task)
    builder.container = task


def _read_table_row(builder: _Builder, line: str) -> None:
    """A row of a markdown table: the header names columns, the body is items."""
    if not builder.table_started:
        builder.table_started = True
        return
    if TABLE_SEPARATOR_RE.match(line):
        return
    cells = _table_cells(line)
    first = cells[0] if cells else ""
    rest = " ".join(cell for cell in cells[1:] if cell).strip()
    item = ParsedItem(
        kind=KIND_TABLE_ROW,
        text_md=rest or first,
        html_form=FORM_TABLE_ROW,
        table_when=first or None,
    )
    if rest:
        window, comment = split_window(first)
        if window is not None:
            item.window = window
            item.window_comment = comment
        else:
            # «до 20:00», «первым делом», «ночью» — a when that is not a clock
            # reading. It is the row's handle, and the exporter puts it back into
            # the first column.
            item.code = first or None
    builder.add_item(item, depth=0)


def _read_list_line(builder: _Builder, match: re.Match[str], *, ordered: bool) -> None:
    depth = _depth(match.group("indent"))
    body = match.group("body").strip()
    if FIELD_SEPARATOR in body:
        label, value = body.split(FIELD_SEPARATOR, 1)
        builder.add_field(label, value, depth)
        return
    kind = _item_kind(builder, ordered=ordered, depth=depth)
    builder.add_item(
        ParsedItem(kind=kind, text_md=body, html_form=FORM_LIST_ITEM), depth
    )
