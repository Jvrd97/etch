"""
Tests for the import of the `personal-os` history.

Every acceptance case of `#89` is here, in the words of the ticket: the plans of
August open on `/day/{date}`; a second run changes nothing; the marks of the
saved `.html` land on the lines they were made against and the ones that find no
line are named with their key and their file; a day nobody opened has no marks
and no `opened_at`; the days between the plans exist without a plan; no
`Подпись :: значение` is lost; every file read is stored whole with its sha256
and nothing under the root is written to; and exporting a day and importing it
again gives the same plan.

The fixture under `tests/fixtures/personal_os/` is the live 28 August — the
`.md`, the `.html` a person actually ticked, and the `.report.md`
`plan_server.py` wrote beside them — plus two small days written for the cases
the live data does not contain, and three live `summaries/**` for the verdicts
`#90` imports as prose.
"""

# [review:need-review] PHASE-03/89, PHASE-03/90
# summary: tests of the personal-os import — the markdown grammar, the mark keys of a rendered page (schedule rows included), idempotence at row level, the calendar without holes, the labels that survive, the export/import round trip, and the summaries whose verdicts arrive as prose and are never recomputed
import hashlib
import shutil
from collections.abc import AsyncGenerator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.daytime import day_bounds
from app.crud import day as day_crud
from app.crud import mark as mark_crud
from app.crud import plan as plan_crud
from app.crud import summary as summary_crud
from app.day.evaluate import VERDICT_LOST
from app.exports.personal_os import export_day
from app.imports.md_parser import match_key, parse_plan, split_window
from app.imports.personal_os import (
    ImportReport,
    build_document,
    collect_days,
    import_root,
    read_verdict,
)
from app.imports.plan_state import (
    is_exported_report,
    read_day_report,
    read_plan_state,
)
from app.models.import_source import ImportSource
from app.models.mark import PlanMark
from app.models.plan import DayPlan, PlanItem, PlanSection
from app.models.summary import SOURCE_IMPORT, DaySummary

FIXTURES = Path(__file__).parent / "fixtures" / "personal_os"
PLANS = FIXTURES / "plans" / "2026" / "08"

LIVE_DAY = date(2026, 8, 28)
UNOPENED_DAY = date(2026, 8, 26)
STALE_MARK_DAY = date(2026, 8, 24)

# The three summaries in the fixture. 14 August was lived under the legacy canon
# (ceiling of ten hours, bar of 80%), the other two under the current one.
LEGACY_SUMMARY = date(2026, 8, 14)
OFF_SUMMARY = date(2026, 8, 20)


@pytest.fixture(autouse=True)
async def seeded_rules(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    """The rule table as a migrated database has it; `create_all` has no seed."""
    await day_crud.seed_rules(db_session)
    await day_crud.list_rules(db_session)
    yield


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A copy of the fixture repository, so a test can prove nothing wrote to it."""
    copied = tmp_path / "personal-os"
    shutil.copytree(FIXTURES, copied)
    return copied


def live_plan_text() -> str:
    return (PLANS / f"{LIVE_DAY.isoformat()}.md").read_text(encoding="utf-8")


def live_page() -> str:
    return (PLANS / f"{LIVE_DAY.isoformat()}.html").read_text(encoding="utf-8")


def digests(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


async def rows(session: AsyncSession, on: date) -> list[tuple[Any, ...]]:
    """
    Every row the import owns for one day, as plain values.

    Ids and timestamps included on purpose: "the second run changes nothing" has
    to mean the rows were not rewritten, not that they were rewritten to equal
    values.
    """
    day = await day_crud.get_day(session, on)
    plan = await plan_crud.get_plan(session, on)
    marks = await mark_crud.list_marks(session, on)
    found: list[tuple[Any, ...]] = [
        (day.day_date, day.opened_at, day.last_touched_at) if day else ()
    ]
    if plan is not None:
        found.append((plan.id, plan.created_at, plan.updated_at, plan.title))
        for section in sorted(plan.sections, key=lambda one: one.ord):
            found.append((section.id, section.ord, section.title, section.kind))
            for item in sorted(section.items, key=lambda one: one.ord):
                found.append((item.id, item.ord, item.kind, item.text_plain))
    for mark in sorted(marks, key=lambda one: one.item_id):
        found.append((mark.item_id, mark.state, mark.note, mark.marked_at))
    return found


# --------------------------------------------------------------- the markdown


def test_the_front_matter_of_a_live_plan_becomes_the_head_of_the_document() -> None:
    plan = parse_plan(live_plan_text(), LIVE_DAY)

    assert plan.title == "Пятница"
    assert plan.title_marker == "в дороге"
    assert plan.lede is not None and plan.lede.startswith("Рабочих окон около четырёх")
    assert plan.counters[0] == "4 = рабочие задачи"
    assert [section.kind for section in plan.sections[:4]] == [
        "anchors",
        "training",
        "hard_points",
        "work",
    ]


def test_a_task_carries_its_window_its_criterion_and_its_own_labels() -> None:
    plan = parse_plan(live_plan_text(), LIVE_DAY)
    tasks = [item for item in plan.items() if item.kind == "task"]

    first = tasks[0]
    assert first.code == "W1"
    assert first.window == "12:00-14:00"
    assert first.window_comment == "пока ногти. 1.5-2 ч."
    assert first.done_criterion is not None and first.done_criterion.startswith("Файл")
    assert [child.kind for child in first.children] == ["minimum"]


def test_a_window_drops_the_duration_it_repeats_and_keeps_the_comment() -> None:
    """
    Only the duration written immediately after the window goes — the window
    already states it. A sentence that happens to end in one is a sentence.
    """
    assert split_window("08:30-11:15, 2 ч 45 мин. Первый блок") == (
        "08:30-11:15",
        "Первый блок",
    )
    assert split_window("12:00-14:00, пока ногти. 1.5-2 ч.") == (
        "12:00-14:00",
        "пока ногти. 1.5-2 ч.",
    )
    assert split_window("~09:30-11:00") == ("09:30-11:00", None)
    assert split_window("первым делом") == (None, "первым делом")


def test_a_table_row_keeps_the_column_that_is_not_a_clock_reading() -> None:
    plan = parse_plan(live_plan_text(), LIVE_DAY)
    table = [item for item in plan.items() if item.kind == "table_row"]

    by_text = {item.text_md: item for item in table}
    assert by_text["Дорога"].code == "ночью"
    assert by_text["Выезд"].code == "~09:30"


def test_a_details_block_is_not_guessed_at_and_is_named_instead() -> None:
    plan = parse_plan(live_plan_text(), LIVE_DAY)

    assert any(line.startswith("<details") for line in plan.unparsed)
    assert not any("<details" in item.text_md for item in plan.items())


def test_no_label_of_the_live_plan_is_lost() -> None:
    """Every `Подпись :: значение` is either a column or a key of `extra`."""
    plan = parse_plan(live_plan_text(), LIVE_DAY)
    columns = {
        "Окно": [item.window for item in plan.items()],
        "Сделано": [item.done_criterion for item in plan.items()],
        "Ход": [item.plan_md for item in plan.items()],
        "Почему": [item.why_md for item in plan.items()],
        "Минимум": [item.text_md for item in plan.items() if item.kind == "minimum"],
    }
    written = {
        line.split(" :: ", 1)[0].lstrip("- ").strip()
        for line in live_plan_text().splitlines()
        if line.strip().startswith("- ") and " :: " in line
    }

    for label in written:
        if label in columns:
            assert any(columns[label]), f"подпись «{label}» потеряна"
            continue
        in_extra = any(label in item.extra for item in plan.items())
        assert in_extra, f"подпись «{label}» не доехала ни в колонку, ни в extra"


# ------------------------------------------------------- the marks of a page


def test_the_keys_of_a_page_count_the_generated_schedule_and_skip_its_header() -> None:
    """
    `t7` is the first row a person wrote, because seven rows above it are
    generated. Counting `<tr>` without that offset — or counting the `<thead>`
    row of every table — puts the mark of «~09:30 Выезд» on another line.
    """
    state = read_plan_state(live_page())
    assert state is not None

    table_keys = [row for row in state.keys if row.key.startswith("t")]
    schedule = [row for row in table_keys if row.alias_of is not None]
    assert [row.key for row in schedule] == [f"t{index}" for index in range(7)]

    written = table_keys[len(schedule)]
    assert written.key == "t7"
    assert written.alias_of is None
    assert written.signature.startswith(match_key("07:45 Первым делом"))


def test_a_notebook_with_a_raw_newline_is_still_read() -> None:
    state = read_plan_state(live_page())

    assert state is not None
    assert state.notebook is not None
    assert "спать в 2349" in state.notebook


def test_a_page_that_was_never_opened_with_the_server_has_no_state() -> None:
    assert read_plan_state("<html><body><main></main></body></html>") is None


def test_the_report_plan_server_wrote_is_not_read_as_an_exported_one() -> None:
    """
    Its lists are derived from the `.html` beside it. Reading both would import
    the same ticks twice, under two different mappings.
    """
    text = (PLANS / f"{LIVE_DAY.isoformat()}.report.md").read_text(encoding="utf-8")

    assert text.lstrip().startswith("# Отчёт дня")
    assert not is_exported_report(text)
    assert read_day_report(text) is None


def test_an_exported_report_is_read_back_into_marks_a_time_and_a_notebook() -> None:
    report = read_day_report(
        "# Как прошло — 2026-08-28 (пт)\n"
        "\n"
        "- Открыт :: 08:12\n"
        "\n"
        "## Отметки\n"
        "\n"
        "| Пункт | Итог | Как прошло |\n"
        "|---|---|---|\n"
        "| W1 · Шортлист | сделано | успел |\n"
        "| Витамины. | не сделано |  |\n"
        "\n"
        "## Блокнот\n"
        "\n"
        "две строки\nвторая\n"
    )

    assert report is not None
    assert report.opened_at_local is not None
    assert (report.opened_at_local.hour, report.opened_at_local.minute) == (8, 12)
    assert [(one.state, one.note) for one in report.marks] == [
        ("done", "успел"),
        ("failed", None),
    ]
    assert report.notebook == "две строки\nвторая"


# -------------------------------------------------------------- the database


async def test_a_plan_of_august_opens_on_its_day_url(
    db_session: AsyncSession, client: AsyncClient, root: Path
) -> None:
    await import_root(db_session, root)

    response = await client.get(f"/api/v1/day/{LIVE_DAY.isoformat()}")

    assert response.status_code == 200
    body = response.json()
    assert body["plan"] is not None
    titles = [section["title"] for section in body["plan"]["sections"]]
    assert "Якоря" in titles
    assert "Жёсткие точки дня" in titles
    assert any(
        item["code"] == "W1"
        for section in body["plan"]["sections"]
        for item in section["items"]
    )


async def test_a_second_run_does_not_touch_a_single_row(
    db_session: AsyncSession, root: Path
) -> None:
    first = await import_root(db_session, root)
    before = await rows(db_session, LIVE_DAY)

    second = await import_root(db_session, root)

    assert first.written == 3
    assert (second.written, second.items_written, second.marks_written) == (0, 0, 0)
    assert second.unchanged == 3
    assert second.warnings == []
    assert await rows(db_session, LIVE_DAY) == before


async def test_a_mark_lands_on_the_line_it_was_made_against(
    db_session: AsyncSession, root: Path
) -> None:
    await import_root(db_session, root)

    plan = await plan_crud.get_plan(db_session, LIVE_DAY)
    assert plan is not None
    by_text = {
        item.text_plain: item for section in plan.sections for item in section.items
    }
    marks = {
        mark.item_id: mark for mark in await mark_crud.list_marks(db_session, LIVE_DAY)
    }

    assert marks[by_text["Выезд"].id].state == "done"
    assert marks[by_text["Шортлист 5 кандидатов на backend"].id].state == "done"
    assert marks[by_text["Ногти — я с ноутом. Это рабочее окно, а не пауза."].id].state
    assert by_text["Витамины."].id in marks
    assert all(mark.source == "import" for mark in marks.values())


async def test_the_schedule_copy_of_a_tick_does_not_overrule_the_line_itself(
    db_session: AsyncSession, root: Path
) -> None:
    """
    28 August was ticked twice in places: once on the generated schedule row and
    once on the hard point it was generated from, and the two disagree. The line
    wins, and the disagreement is reported rather than resolved silently.
    """
    report = await import_root(db_session, root)

    plan = await plan_crud.get_plan(db_session, LIVE_DAY)
    assert plan is not None
    nails = next(
        item
        for section in plan.sections
        for item in section.items
        if item.text_plain.startswith("Ногти")
    )
    mark = next(
        one
        for one in await mark_crud.list_marks(db_session, LIVE_DAY)
        if one.item_id == nails.id
    )

    assert mark.state == "failed"
    assert any(
        warning.kind == "расписание спорит со строкой" for warning in report.warnings
    )


async def test_a_mark_that_finds_no_line_is_named_with_its_key_and_its_file(
    db_session: AsyncSession, root: Path
) -> None:
    report = await import_root(db_session, root)

    orphan = [one for one in report.warnings if one.kind == "отметка без пункта"]
    assert len(orphan) == 1
    assert orphan[0].key == "i2"
    assert orphan[0].path == "plans/2026/08/2026-08-24.html"
    assert "2026-08-24.html" in orphan[0].as_line()


async def test_the_file_of_an_unmatched_mark_is_still_in_the_database(
    db_session: AsyncSession, root: Path
) -> None:
    await import_root(db_session, root)

    stored = await db_session.execute(
        select(ImportSource.raw).where(
            ImportSource.path == "plans/2026/08/2026-08-24.html"
        )
    )
    raw = stored.scalar_one()
    assert "этой строки больше нет" in raw


async def test_a_day_nobody_opened_has_no_marks_and_no_opened_at(
    db_session: AsyncSession, root: Path
) -> None:
    """
    The plan of 26 August is there in full; nobody ever ticked it. That is a
    different fact from "did nothing", and `#88` made it expressible.
    """
    await import_root(db_session, root)

    day = await day_crud.get_day(db_session, UNOPENED_DAY)
    plan = await plan_crud.get_plan(db_session, UNOPENED_DAY)

    assert day is not None and day.opened_at is None
    assert plan is not None and plan.sections
    assert await mark_crud.list_marks(db_session, UNOPENED_DAY) == []


async def test_a_day_that_was_ticked_is_marked_as_opened_inside_that_day(
    db_session: AsyncSession, root: Path
) -> None:
    await import_root(db_session, root)

    day = await day_crud.get_day(db_session, LIVE_DAY)

    assert day is not None and day.opened_at is not None
    start, end = day_bounds(LIVE_DAY)
    assert start <= day.opened_at < end


async def test_the_calendar_between_the_first_and_the_last_plan_has_no_holes(
    db_session: AsyncSession, root: Path
) -> None:
    report = await import_root(db_session, root)

    assert [one.isoformat() for one in report.gaps_filled] == [
        "2026-08-25",
        "2026-08-27",
    ]
    for day_date in (date(2026, 8, 25), date(2026, 8, 27)):
        day = await day_crud.get_day(db_session, day_date)
        assert day is not None
        assert await plan_crud.get_plan(db_session, day_date) is None


async def test_every_file_read_is_stored_whole_with_its_digest(
    db_session: AsyncSession, root: Path
) -> None:
    await import_root(db_session, root)

    stored = await db_session.execute(select(ImportSource))
    sources = {one.path: one for one in stored.scalars().all()}

    assert set(sources) == set(digests(root))
    for path, source in sources.items():
        on_disk = (root / path).read_text(encoding="utf-8")
        assert source.raw == on_disk
        assert source.sha256 == hashlib.sha256(on_disk.encode("utf-8")).hexdigest()


async def test_the_import_writes_nothing_under_its_root(
    db_session: AsyncSession, root: Path
) -> None:
    before = digests(root)

    await import_root(db_session, root)

    assert digests(root) == before


async def test_a_task_the_canon_would_refuse_is_kept_as_a_line_and_reported(
    db_session: AsyncSession, root: Path
) -> None:
    """
    `### W3 · Документы` has no window: it cannot be a task, and refusing the
    whole day over it would lose 28 August. It stays a line, keeps its handle in
    its text, and the downgrade is named.
    """
    report = await import_root(db_session, root)

    plan = await plan_crud.get_plan(db_session, LIVE_DAY)
    assert plan is not None
    texts = [item.text_plain for section in plan.sections for item in section.items]

    assert "W3 · Документы" in texts
    assert any(
        one.kind == "задача понижена до пункта" and "W3" in one.message
        for one in report.warnings
    )


async def test_a_link_to_another_plan_becomes_a_link_to_that_day(
    db_session: AsyncSession, root: Path
) -> None:
    plan = parse_plan(
        "# План 2026-08-24 (пн)\n\n## Якоря\n\n"
        "- Завтра — [план](2026-08-25.md), неделя — [W35](../../../weeks/2026/2026-W35.md)\n",
        STALE_MARK_DAY,
    )
    report = ImportReport(root=Path("."))
    document = build_document(plan, warnings=report.warnings, where="x.md", ids={})

    text = document.sections[0].items[0].text_md
    assert "](/day/2026-08-25)" in text
    assert "](../../../weeks/2026/2026-W35.md)" in text
    assert any(one.kind == "ссылка не переписана" for one in report.warnings)


async def test_exporting_a_day_and_importing_it_again_gives_the_same_plan(
    db_session: AsyncSession, root: Path, tmp_path: Path
) -> None:
    """
    The round trip `#89` owes ADR-0014: the export is the rollback insurance, and
    insurance that cannot be read back is not insurance.
    """
    await import_root(db_session, root)
    before = await shape(db_session, LIVE_DAY)
    marks_before = len(await mark_crud.list_marks(db_session, LIVE_DAY))

    out = tmp_path / "archive"
    await export_day(db_session, LIVE_DAY, out)
    report = await import_root(db_session, out, force=True, only=LIVE_DAY)

    assert report.written == 1
    assert await shape(db_session, LIVE_DAY) == before
    assert len(await mark_crud.list_marks(db_session, LIVE_DAY)) == marks_before
    notebook = await day_crud.get_notebook(db_session, LIVE_DAY)
    assert notebook is not None and "спать в 2349" in notebook.content


async def shape(session: AsyncSession, on: date) -> list[tuple[Any, ...]]:
    """The plan as structure and content, with no ids and no timestamps in it."""
    plan = await plan_crud.get_plan(session, on)
    assert plan is not None
    by_id = {item.id: item for section in plan.sections for item in section.items}

    def node(item: PlanItem) -> tuple[Any, ...]:
        children = sorted(
            (one for one in by_id.values() if one.parent_id == item.id),
            key=lambda one: one.ord,
        )
        return (
            item.kind,
            item.text_plain,
            item.code,
            item.done_criterion,
            item.why_md,
            item.plan_md,
            item.unlinked_reason,
            tuple(sorted((item.extra or {}).items())),
            item.starts_at,
            item.ends_at,
            item.window_comment,
            tuple(node(one) for one in children),
        )

    found: list[tuple[Any, ...]] = [(plan.title, plan.title_marker, plan.lede)]
    for section in sorted(plan.sections, key=lambda one: one.ord):
        roots = sorted(
            (one for one in section.items if one.parent_id is None),
            key=lambda one: one.ord,
        )
        found.append((section.ord, section.title, section.kind))
        found.extend(node(one) for one in roots)
    return found


async def test_the_days_of_the_fixture_are_the_three_plans_it_holds(
    root: Path,
) -> None:
    """A `.bak`, a `.report.md` and a file whose name is not a date are not plans."""
    (root / "plans" / "2026" / "08" / "2026-08-24.md.bak").write_text("x", "utf-8")
    (root / "plans" / "2026" / "08" / "notes 13.08.2026.md").write_text("x", "utf-8")

    assert [one.day_date for one in collect_days(root)] == [
        STALE_MARK_DAY,
        UNOPENED_DAY,
        LIVE_DAY,
    ]


async def test_the_plan_the_import_wrote_is_marked_as_imported(
    db_session: AsyncSession, root: Path
) -> None:
    await import_root(db_session, root)

    stored = await db_session.execute(
        select(DayPlan.source, DayPlan.raw_md).where(DayPlan.day_date == LIVE_DAY)
    )
    source, raw_md = stored.one()

    assert source == "import"
    assert raw_md == live_plan_text()


async def test_every_line_of_the_day_is_recognisable_on_a_second_reading(
    db_session: AsyncSession, root: Path
) -> None:
    """
    `legacy_key` is what a re-run recognises a row by: the key of the rendered
    page where there was one, a positional handle where there was not. Without
    it a forced re-import mints new uuids and the marks of `#88` fall off.
    """
    await import_root(db_session, root)
    before = {
        item.legacy_key: item.id
        for item in (await plan_crud.get_plan(db_session, LIVE_DAY)).sections[0].items
    }

    await import_root(db_session, root, force=True, only=LIVE_DAY)
    after = {
        item.legacy_key: item.id
        for item in (await plan_crud.get_plan(db_session, LIVE_DAY)).sections[0].items
    }

    assert None not in before
    assert before == after


async def test_a_forced_re_import_keeps_the_marks_of_the_day(
    db_session: AsyncSession, root: Path
) -> None:
    await import_root(db_session, root)
    before = len(await mark_crud.list_marks(db_session, LIVE_DAY))

    await import_root(db_session, root, force=True)

    assert len(await mark_crud.list_marks(db_session, LIVE_DAY)) == before


async def test_the_sections_and_items_of_the_live_day_are_all_stored(
    db_session: AsyncSession, root: Path
) -> None:
    await import_root(db_session, root)

    sections = await db_session.execute(
        select(PlanSection.title)
        .join(DayPlan, DayPlan.id == PlanSection.plan_id)
        .where(DayPlan.day_date == LIVE_DAY)
        .order_by(PlanSection.ord)
    )
    items = await db_session.execute(
        select(PlanItem.id)
        .join(PlanSection, PlanSection.id == PlanItem.section_id)
        .join(DayPlan, DayPlan.id == PlanSection.plan_id)
        .where(DayPlan.day_date == LIVE_DAY)
    )
    marks = await db_session.execute(select(PlanMark.item_id))

    assert list(sections.scalars().all())[:3] == [
        "Якоря",
        "Тренировка — верх тела, pull в приоритете",
        "Жёсткие точки дня",
    ]
    assert len(items.scalars().all()) > 30
    assert len(marks.scalars().all()) == 17


# ------------------------------------------------------------- the summaries


def test_the_verdict_is_read_out_of_the_first_bold_fragment_of_the_line() -> None:
    """
    The one regular expression that reads a verdict, and where it stops.

    `life.py` matched `\\*\\*(да|нет)` — the bold had to *start* with the word.
    «**Формально — нет.**» is the verdict of 28 August and would have fallen
    through into `None`, which is the answer for a day nobody judged. So the
    search is for да/нет *inside* the first bold fragment of the line, and a
    line with no bold at all — «Вне игры (выходной)» — still has no verdict.
    """
    assert read_verdict("## День выигран?\n\n**Нет.** Якоря 1/5\n") == VERDICT_LOST
    assert read_verdict("## День выигран?\n\n**Формально — нет.** Задачи 4/4\n") == (
        VERDICT_LOST
    )
    assert read_verdict("## День выигран?\n\n**Да.** Всё закрыто\n") == "won"
    assert (
        read_verdict("## День выигран?\n\nВне игры (выходной). Учебная — да\n") is None
    )
    assert read_verdict("# План\n\nникакого раздела нет\n") is None


async def test_the_summaries_of_august_arrive_with_their_prose_and_their_verdicts(
    db_session: AsyncSession, root: Path
) -> None:
    report = await import_root(db_session, root)

    stored = {
        row.day_date: row
        for row in (await db_session.execute(select(DaySummary))).scalars().all()
    }

    assert report.summaries_written == 3
    assert set(stored) == {LEGACY_SUMMARY, OFF_SUMMARY, LIVE_DAY}
    assert stored[LIVE_DAY].verdict == VERDICT_LOST
    assert "Формально — нет" in stored[LIVE_DAY].body_md
    # «Вне игры (выходной)» — никто не судил этот день, и это не проигрыш.
    assert stored[OFF_SUMMARY].verdict is None
    assert all(row.source == SOURCE_IMPORT for row in stored.values())


async def test_an_imported_summary_names_the_canon_the_day_was_lived_under(
    db_session: AsyncSession, root: Path
) -> None:
    """
    `day_summary.rule_set_id` совпадает с `day.rule_set_id` той же даты.

    ADR-0014 says imported verdicts carry `rule_set = legacy`, and that reading
    would be a lie for 20 and 28 August: they were lived after 2026-08-17, under
    the current canon. «Не пересчитывать» is expressed by `source='import'`, and
    it holds for every date rather than only for the ones before the change.
    """
    await import_root(db_session, root)

    for on in (LEGACY_SUMMARY, OFF_SUMMARY, LIVE_DAY):
        day = await day_crud.get_day(db_session, on)
        stored = await summary_crud.get_summary(db_session, on)
        assert day is not None and stored is not None
        assert stored.rule_set_id == day.rule_set_id, on.isoformat()

    legacy = await summary_crud.get_summary(db_session, LEGACY_SUMMARY)
    current = await summary_crud.get_summary(db_session, LIVE_DAY)
    assert legacy is not None and current is not None
    assert legacy.rule_set_id != current.rule_set_id


async def test_a_recompute_never_rewrites_a_verdict_that_arrived_as_prose(
    db_session: AsyncSession, root: Path
) -> None:
    """
    Пересчёт истории дважды подряд оставляет те же значения.

    An imported day has no marks and no measured work: re-judging it would
    replace a person's sentence with zeros. Only `streak_after` — derived by
    definition — is written onto such a row.
    """
    await import_root(db_session, root)
    before = await verdicts(db_session)

    await summary_crud.recompute_history(db_session)
    once = await verdicts(db_session)
    await summary_crud.recompute_history(db_session)

    assert once == before
    assert await verdicts(db_session) == before


async def test_a_second_run_of_the_import_changes_no_summary_either(
    db_session: AsyncSession, root: Path
) -> None:
    await import_root(db_session, root)
    before = await verdicts(db_session)

    second = await import_root(db_session, root)

    assert second.summaries_written == 0
    assert await verdicts(db_session) == before


async def test_the_prose_of_a_summary_is_findable_by_a_phrase_from_it(
    db_session: AsyncSession, root: Path
) -> None:
    """«Поиск по прозе итогов находит день по фразе» — раздел «куда разъехался день»."""
    await import_root(db_session, root)

    found = await summary_crud.search(db_session, "срыв отбоя стоял в плане дня")

    assert [row.day_date for row in found] == [LIVE_DAY]
    assert await summary_crud.search(db_session, "квантовая хромодинамика") == []


async def verdicts(session: AsyncSession) -> list[tuple[Any, ...]]:
    """Every summary as plain values — verdict, reason, counters, streak."""
    result = await session.execute(select(DaySummary).order_by(DaySummary.day_date))
    return [
        (
            row.day_date,
            row.verdict,
            row.verdict_reason,
            row.rule_set_id,
            row.tasks_done,
            row.tasks_total,
            row.streak_after,
            row.body_md,
        )
        for row in result.scalars().all()
    ]


def test_the_summaries_of_the_fixture_are_the_three_files_it_holds(root: Path) -> None:
    found = sorted(
        date.fromisoformat(path.stem) for path in (root / "summaries").rglob("*.md")
    )

    assert found == [LEGACY_SUMMARY, OFF_SUMMARY, LIVE_DAY]


def test_only_the_importer_reads_a_verdict_out_of_prose() -> None:
    """
    Ни один код вне `app/imports/` не разбирает вердикт регуляркой.

    That was the whole complaint of `#90`: `life.py` and `plan_server.py` each
    had their own copy, and the criterion itself existed in three incompatible
    versions. Here the prose is read in exactly one file, and everything
    downstream works with the value.
    """
    app_root = Path(__file__).parent.parent / "app"
    # The alternation of the two words is what a verdict parser is made of;
    # prose *about* the heading (`app/day/evaluate.py` explains where the
    # criterion came from) is not a second parser.
    offenders = [
        str(path.relative_to(app_root))
        for path in sorted(app_root.rglob("*.py"))
        if "imports" not in path.parts and "да|нет" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []
