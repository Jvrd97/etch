# [review:need-review] PHASE-03/94
# summary: `weeks/YYYY/YYYY-Www.md` read into the week snapshot — «Что мешало», «Mgmt-ретро» and the weekly figure into their own columns, everything else left as `retro_md`, the sunday checklist unrolled into rows, and the counters never taken from the prose
"""
A file of `weeks/` as a week row.

A module of its own for the reason `goal_md` is one: `app.imports.personal_os`
is a thousand lines about days, and a week file is read by different rules —
four prose blocks and one checklist.

**Счётчики из прозы не берутся.** The file says «0 из 7» and «Стрик 0», and
neither number is written to a column: `recompute_week` reads them off
`day_summary`. The sentence a person wrote stays in `retro_md`, where it is a
statement about the moment it was written; the columns stay a snapshot that can
be taken again. Reading the prose into the columns would give one week two
answers with nothing saying which is current.

**Три раздела уезжают в свои колонки, остальное остаётся ретро.** «Что мешало»
and «Mgmt-ретро» are read separately often enough — one is «почему неделя
провалилась», the other is «на тот ли холм лезем» — that a search returning the
whole file for either is a worse answer than two columns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.day.week import ISO_CODE_RE
from app.schemas.week import WeekIn, WeekReviewItemIn

__all__ = ["ParsedWeek", "iso_from_name", "parse_week"]

# `## Что мешало` — a heading of the second level starts every block a week file
# is made of. `###` inside a block belongs to it and is not a boundary.
HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)

# `- [x] **Решить: SQLite …**` — one line of «На разбор в воскресенье», with the
# tick that says whether Sunday actually answered it.
CHECKBOX_RE = re.compile(r"^\s*[-*]\s*\[([ xX])\]\s*(.+)$")

# Headings whose body goes into a column of its own rather than into `retro_md`.
# Matched case-insensitively on the normalised heading text, so «Mgmt-ретро» and
# «MGMT-ретро» are one heading rather than two.
BLOCKERS_HEADINGS = ("что мешало",)
MGMT_HEADINGS = ("mgmt-ретро", "mgmt ретро", "управленческое ретро")
WEEKLY_NUMBER_HEADINGS = (
    "недельный отчёт",
    "недельное число",
    "цифра недели",
    "уравнение расходов и ценности",
)
REVIEW_HEADINGS = ("на разбор в воскресенье", "на разбор")


@dataclass
class ParsedWeek:
    """One week file, split into the columns it becomes."""

    iso_code: str
    retro_md: str = ""
    blockers_md: str = ""
    mgmt_retro_md: str = ""
    weekly_number_md: str = ""
    review_items: list[WeekReviewItemIn] = field(default_factory=list)

    def as_body(self) -> WeekIn:
        """The parsed file in the shape `PUT /weeks/{iso}` takes."""
        return WeekIn(
            retro_md=self.retro_md,
            blockers_md=self.blockers_md,
            mgmt_retro_md=self.mgmt_retro_md,
            weekly_number_md=self.weekly_number_md,
            review_items=list(self.review_items),
        )


def iso_from_name(stem: str) -> str | None:
    """
    The week code a file name carries, or None when it carries none.

    `weeks/2026/2026-W35.md` is the only shape the repository uses; anything
    else in that directory is left alone rather than guessed at.
    """
    return stem if ISO_CODE_RE.match(stem) else None


def _blocks(text: str) -> list[tuple[str, str]]:
    """
    The file as `(heading, body)` pairs, with the preamble under an empty heading.

    The preamble is the two paragraphs above the first `##` — «Файл заведён
    заранее», «Неделя закрыта 30.08» — and dropping it would lose the note that
    says who wrote the retro.
    """
    matches = list(HEADING_RE.finditer(text))
    if not matches:
        return [("", text.strip())]

    blocks: list[tuple[str, str]] = []
    preamble = text[: matches[0].start()].strip()
    if preamble:
        blocks.append(("", preamble))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        blocks.append((match.group(1).strip(), text[match.end() : end].strip()))
    return blocks


def _review_items(body: str) -> list[WeekReviewItemIn]:
    """The checklist of a block, in file order, ticks and all."""
    items: list[WeekReviewItemIn] = []
    for line in body.splitlines():
        match = CHECKBOX_RE.match(line)
        if match is not None:
            items.append(
                WeekReviewItemIn(
                    text_md=match.group(2).strip(),
                    done=match.group(1).lower() == "x",
                )
            )
    return items


def _matches(heading: str, known: tuple[str, ...]) -> bool:
    """Whether a heading is one of `known`, ignoring case and the leading number."""
    normalised = heading.strip().lower()
    return any(normalised.startswith(candidate) for candidate in known)


def parse_week(iso: str, text: str) -> ParsedWeek:
    """
    Read one `weeks/**/*.md` into the columns of a week row.

    Every block the file has ends up somewhere: three named headings go to their
    own columns, «На разбор в воскресенье» becomes checklist rows *and* keeps its
    prose in `retro_md` (the block carries the reasoning around the ticks, and
    dropping it would lose why a question was answered the way it was), and
    everything else — «Выигранные дни», «Стрик», «Переносы», the preamble — is
    joined back into `retro_md` in file order.
    """
    parsed = ParsedWeek(iso_code=iso)
    retro: list[str] = []

    for heading, body in _blocks(text):
        if _matches(heading, BLOCKERS_HEADINGS):
            parsed.blockers_md = body
            continue
        if _matches(heading, MGMT_HEADINGS):
            parsed.mgmt_retro_md = body
            continue
        if _matches(heading, WEEKLY_NUMBER_HEADINGS):
            parsed.weekly_number_md = body
            continue
        if _matches(heading, REVIEW_HEADINGS):
            parsed.review_items = _review_items(body)
        retro.append(f"## {heading}\n\n{body}" if heading else body)

    parsed.retro_md = "\n\n".join(part for part in retro if part).strip()
    return parsed
