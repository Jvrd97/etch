"""
Tests for the export of a stored day back into `plans/YYYY/MM/*.md`.

The acceptance case of `#96` this file carries is «открытый глазами файл
читается как план дня»: a plan sent through the API and read back out of the
database has to come out as markdown with the front matter, the sections, the
windows on the wall clock and the `Подпись :: значение` lines it went in with.
The rest of the file guards the properties that make a weekly archive worth
having — the same day exports to the same bytes, a day without a plan writes no
plan file, and what happened to the plan lands in `.report.md` beside it rather
than inside the plan text.
"""

# [review:need-review] PHASE-03/96, PHASE-03/93
# summary: tests for app.exports.personal_os — the rendered plan, the wall-clock window, the report of marks and notebook, byte-stability between two exports, the day with no plan, and the week folder the cron job writes
from collections.abc import AsyncGenerator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import day as day_crud
from app.crud import plan as plan_crud
from app.exports.personal_os import (
    export_day,
    export_week,
    render_plan,
    week_of,
    week_range,
)

DAY_URL = "/api/v1/day"

# A Monday under the current canon — the same day `#87` and `#88` test against.
EXPORT_DAY = date(2026, 8, 31)
DAY_PATH = f"{DAY_URL}/{EXPORT_DAY.isoformat()}"
PLAN_URL = f"{DAY_PATH}/plan"


@pytest.fixture(autouse=True)
async def seeded_rules(
    db_session: AsyncSession, seeded_goal: int
) -> AsyncGenerator[None, None]:
    """
    The rule table as a migrated database has it; `create_all` has no seed.

    `seeded_goal` comes with it: the exported task names goal 1 of the quarter,
    and since `#93` that column has a foreign key.
    """
    await day_crud.seed_rules(db_session)
    yield


def full_document() -> dict[str, Any]:
    """A plan using every shape the renderer has a branch for."""
    return {
        "title": "Понедельник",
        "title_marker": "без работы",
        "lede": "Короткий день, три задачи",
        "purpose_md": "Q3-пункт 2 — перевожу бизнес в задачи для других",
        "counters": ["1 = рабочая задача", "16:00 = стоп работы"],
        "sections": [
            {
                "kind": "anchors",
                "title": "Якоря",
                "items": [
                    {"kind": "anchor", "code": "подъём", "text_md": "Подъём 06:00"},
                    {"kind": "anchor", "text_md": "Витамины"},
                ],
            },
            {
                "kind": "hard_points",
                "title": "Жёсткие точки дня",
                "items": [
                    {
                        "kind": "hard_point",
                        "rigidity": "hard",
                        "text_md": "Созвон с Игорем",
                        "window": "11:00-11:30",
                    },
                    {
                        "kind": "hard_point",
                        "rigidity": "hard",
                        "text_md": "Ревью дня",
                        "window": "15:40-16:00",
                    },
                ],
            },
            {
                "kind": "work",
                "title": "Работа — по порядку",
                "items": [
                    {
                        "kind": "task",
                        "code": "W1",
                        "text_md": "Шортлист кандидатов",
                        "window": "09:30-11:00",
                        "window_comment": "пока ногти",
                        "plan_md": "Скачать резюме → прогнать по критериям",
                        "done_criterion": "Файл: 5 кандидатов",
                        "why_md": "Пятничный якорь",
                        "quarter_goal_id": 1,
                        "external_ref": {"clickup": "https://app.clickup.com/t/86cb"},
                        "extra": {"формат": "аудио"},
                        "children": [
                            {
                                "kind": "minimum",
                                "text_md": "Резюме скачаны в один файл",
                            }
                        ],
                    }
                ],
            },
            {
                "kind": "training",
                "title": "Тренировка",
                "items": [
                    {"kind": "step", "text_md": "Разминка"},
                    {"kind": "step", "text_md": "Подтягивания 3x8"},
                ],
            },
            {
                "kind": "free",
                "title": "Свободный вечер",
                "items": [
                    {"kind": "bullet", "rigidity": "free", "text_md": "Что захочется"}
                ],
            },
        ],
    }


async def post_plan(client: AsyncClient, body: dict[str, Any]) -> dict[str, Any]:
    response = await client.post(PLAN_URL, json=body)
    assert response.status_code == 201, response.text
    return dict(response.json())


async def rendered(client: AsyncClient, db_session: AsyncSession) -> str:
    """The stored plan of `EXPORT_DAY` as markdown."""
    plan = await plan_crud.get_plan(db_session, EXPORT_DAY)
    assert plan is not None
    return render_plan(EXPORT_DAY, plan)


async def test_a_stored_plan_reads_back_as_a_plan(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The acceptance case: the exported file reads as a plan of a day."""
    await post_plan(client, full_document())
    text = await rendered(client, db_session)

    # Front matter: the marker sits inside the title, as the live plans wrote it.
    assert text.startswith("---\n")
    assert "title: Понедельник *без работы*" in text
    assert "lede: Короткий день, три задачи" in text
    assert "purpose: Q3-пункт 2 — перевожу бизнес в задачи для других" in text
    assert "counters: 1 = рабочая задача; 16:00 = стоп работы" in text

    # The heading and the sections, in the order they were sent.
    assert "# План 2026-08-31 (пн)" in text
    order = [text.index(f"## {title}") for title in ("Якоря", "Работа — по порядку")]
    assert order == sorted(order)

    # A task is a heading of its own with its labels under it.
    assert "### W1 · Шортлист кандидатов" in text
    assert "- Ход :: Скачать резюме → прогнать по критериям" in text
    assert "- Сделано :: Файл: 5 кандидатов" in text
    assert "- Почему :: Пятничный якорь" in text
    assert "- ClickUp :: https://app.clickup.com/t/86cb" in text
    assert "- Формат :: аудио" in text
    # The children of a task are indented (changed by `#89`): an unindented
    # bullet under a task heading reads equally as a step of the task and as the
    # next line of the section, and the importer has to tell the two apart.
    assert "\n  - Минимум :: Резюме скачаны в один файл" in text

    # Steps are numbered, anchors keep their handle, the free item has no window.
    assert "1. Разминка" in text
    assert "2. Подтягивания 3x8" in text
    assert "- подъём :: Подъём 06:00" in text
    assert "- Витамины" in text
    assert "- Что захочется" in text


async def test_a_window_comes_back_on_the_wall_clock_it_was_written_in(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """
    `09:30-11:00, пока ногти` goes in and comes back out.

    The window is stored as two `timestamptz`; rendering it needs the zone, and
    the zone is read from the boundary of `#107` rather than recomputed here.
    """
    await post_plan(client, full_document())
    text = await rendered(client, db_session)
    assert "- Окно :: 09:30-11:00, пока ногти" in text


async def test_hard_points_collapse_into_one_table(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A run of hard points renders as the two-column table the plans used."""
    document = full_document()
    # `rigidity='hard'` is reserved for the edges of the day (`#87`), and a
    # table row is not one of them.
    document["sections"][1]["items"] = [
        dict(one, kind="table_row", rigidity="soft")
        for one in document["sections"][1]["items"]
    ]
    await post_plan(client, document)
    text = await rendered(client, db_session)

    assert "| Время | Что |" in text
    assert "| 11:00-11:30 | Созвон с Игорем |" in text
    assert "| 15:40-16:00 | Ревью дня |" in text
    # One table, not two: the header appears once.
    assert text.count("| Время | Что |") == 1


async def test_two_exports_of_an_unchanged_day_are_the_same_bytes(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """
    A weekly archive is only diffable if an unchanged day exports identically.

    JSONB does not preserve the order its keys arrived in, so the renderer sorts
    them; without that the same day would churn between two runs.
    """
    await post_plan(client, full_document())
    first = await rendered(client, db_session)
    second = await rendered(client, db_session)
    assert first == second


async def test_a_day_without_a_plan_writes_no_plan_file(
    client: AsyncClient, db_session: AsyncSession, tmp_path: Path
) -> None:
    """
    An empty file would be indistinguishable from an export that lost the plan.

    The day itself is created — `GET /day` does that — so this is the "opened it
    and there was nothing" case, not the "no such day" one.
    """
    response = await client.get(DAY_PATH)
    assert response.status_code == 200, response.text

    exported = await export_day(db_session, EXPORT_DAY, tmp_path)
    assert exported.plan_path is None
    assert list(tmp_path.rglob("*.md")) == [
        one for one in [exported.report_path] if one is not None
    ]


async def test_what_happened_lands_in_the_report_beside_the_plan(
    client: AsyncClient, db_session: AsyncSession, tmp_path: Path
) -> None:
    """
    Marks and the notebook go to `.report.md`; the plan file stays a plan.

    Ticks inside the plan text would be the first thing the re-import of `#89`
    has to strip back out of the lines it matches on.
    """
    stored = await post_plan(client, full_document())
    item_id = stored["sections"][2]["items"][0]["id"]

    marked = await client.put(
        f"{DAY_PATH}/marks/{item_id}",
        json={"state": "done", "note": "успел до созвона"},
    )
    assert marked.status_code == 200, marked.text
    noted = await client.put(
        f"{DAY_PATH}/notebook", json={"content": "День вышел спокойный."}
    )
    assert noted.status_code == 200, noted.text

    exported = await export_day(db_session, EXPORT_DAY, tmp_path)
    assert exported.plan_path is not None
    assert exported.report_path is not None
    assert exported.plan_path.parent == tmp_path / "plans" / "2026" / "08"
    assert exported.plan_path.name == "2026-08-31.md"
    assert exported.report_path.name == "2026-08-31.report.md"

    plan_text = exported.plan_path.read_text(encoding="utf-8")
    report_text = exported.report_path.read_text(encoding="utf-8")

    assert "сделано" not in plan_text
    assert "успел до созвона" not in plan_text
    assert "| W1 · Шортлист кандидатов | сделано | успел до созвона |" in report_text
    assert "## Блокнот" in report_text
    assert "День вышел спокойный." in report_text


async def test_a_day_nobody_opened_gets_no_report_at_all(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """
    The fourth kind of empty of `#88` survives the export.

    An empty report file would put "nobody came" back into the same shape as
    "came and did nothing", which is the distinction the day table exists for.
    """
    exported = await export_day(db_session, EXPORT_DAY, tmp_path)
    assert exported.plan_path is None
    assert exported.report_path is None
    assert list(tmp_path.rglob("*")) == []


async def test_the_week_lands_in_a_folder_named_after_the_week(
    client: AsyncClient, db_session: AsyncSession, tmp_path: Path
) -> None:
    """What `deploy/export-md.sh` produces: `<out>/2026-W36/plans/2026/08/…`."""
    await post_plan(client, full_document())
    start, end = week_range("current", EXPORT_DAY)
    report = await export_week(db_session, tmp_path, start, end)

    assert report.week == "2026-W36"
    assert report.out_dir == tmp_path / "2026-W36"
    assert len(report.days) == 7
    assert report.plans_written == 1
    written = tmp_path / "2026-W36" / "plans" / "2026" / "08" / "2026-08-31.md"
    assert written.is_file()


def test_last_week_is_the_week_that_finished() -> None:
    """
    `--week last` never exports the week still being lived.

    Run on Monday 2026-09-07 it has to hand back the whole previous week, not
    the one that started this morning.
    """
    start, end = week_range("last", date(2026, 9, 7))
    assert (start, end) == (date(2026, 8, 31), date(2026, 9, 6))
    assert week_of(start) == "2026-W36"


def test_an_explicit_week_is_read_as_iso() -> None:
    """`2026-W35` is Monday 24 August to Sunday 30 August."""
    assert week_range("2026-W35", date(2026, 9, 7)) == (
        date(2026, 8, 24),
        date(2026, 8, 30),
    )


def test_a_malformed_week_is_refused_rather_than_guessed() -> None:
    """A typo in the cron line must not silently export some other week."""
    with pytest.raises(ValueError, match="YYYY-Www"):
        week_range("last-week", date(2026, 9, 7))
