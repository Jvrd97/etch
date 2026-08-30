"""
Импорт `training/state.md`: свёрнутая во frontmatter таблица — в строки.

Приёмка тикета читается буквально: «импортированное состояние совпадает с тем,
что было в файле — даты последних тяжёлых, объём недели, пропуски». Совпадает не
потому, что значения перенесены в снимок, а потому, что они выводятся из строк,
которые импорт положил. Разница принципиальная: перенесённый снимок нечем
проверить, выведенный — пересчитывается заново в любой момент.

Единственное, что намеренно **не** переносится, — `skipped_days: 0`. В живом
файле он стоит нулём при трёх ключах `skipped_*`, и это ровно та цена свёрнутой
в YAML таблицы, ради которой тикет и делается.
"""

# [review:need-review] PHASE-03/92
# summary: tests of the training-state import — the dated frontmatter keys become rows, the `last_*` dates are reproduced by the recompute instead of being copied into it, the week counter matches the file, the skipped days match the file (and the file's own stale `skipped_days` does not), complaints and records land once, and a second run adds nothing
import shutil
from collections.abc import AsyncGenerator
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import day as day_crud
from app.crud import training as training_crud
from app.imports.personal_os import import_root
from app.imports.training_state import (
    import_training_state,
    parse_training_state,
)
from app.models.training import COMPLAINT_OPEN
from app.training.state import recompute

FIXTURES = Path(__file__).parent / "fixtures" / "personal_os"
STATE_FILE = FIXTURES / "training" / "state.md"

# The last date the file names — the day its own counters were written on, and
# therefore the day a recompute has to be made on to reproduce them.
LAST_DAY = date(2026, 8, 31)


@pytest.fixture(autouse=True)
async def seeded_rules(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    await day_crud.seed_rules(db_session)
    await day_crud.list_rules(db_session)
    yield


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A copy of the fixture repository, so nothing writes to the original."""
    copied = tmp_path / "personal-os"
    shutil.copytree(FIXTURES, copied)
    return copied


def state_text() -> str:
    return STATE_FILE.read_text(encoding="utf-8")


def test_the_folded_keys_become_days() -> None:
    parsed = parse_training_state(state_text())

    assert parsed.days[date(2026, 8, 12)].planned_md is not None
    assert parsed.days[date(2026, 8, 12)].done_md is not None
    assert parsed.days[date(2026, 8, 29)].skipped is True
    assert parsed.days[date(2026, 8, 30)].skipped is True
    assert parsed.days[date(2026, 8, 14)].skipped is True


def test_the_dated_notes_land_on_their_dates() -> None:
    parsed = parse_training_state(state_text())

    note = parsed.days[date(2026, 8, 10)].note_md
    assert note is not None
    assert "провал объёма" in note
    # Проза одной даты не утекает в соседнюю.
    assert "Ноги+кор" not in note


def test_the_last_heavy_dates_are_stamped_on_the_days_they_name() -> None:
    parsed = parse_training_state(state_text())

    assert "pull" in parsed.days[date(2026, 8, 17)].heavy_patterns
    assert "push" in parsed.days[date(2026, 8, 28)].heavy_patterns
    assert "legs" in parsed.days[date(2026, 8, 12)].patterns
    assert parsed.days[date(2026, 8, 28)].outdoor_done is True


async def test_the_imported_state_matches_the_file(db_session: AsyncSession) -> None:
    # Приёмка тикета. Даты последних тяжёлых и объём недели — из файла; здесь
    # они выведены из строк, а не переписаны в снимок.
    await import_training_state(db_session, state_text())

    rows = await training_crud.list_training_days(db_session)
    snapshot = recompute(
        training_crud.day_facts(rows),
        training_crud.complaint_facts(await training_crud.list_complaints(db_session)),
        LAST_DAY,
    )

    assert snapshot.last_heavy_pull == date(2026, 8, 17)
    assert snapshot.last_heavy_push == date(2026, 8, 28)
    assert snapshot.last_legs == date(2026, 8, 12)
    assert snapshot.last_run == date(2026, 8, 11)
    assert snapshot.last_outdoor == date(2026, 8, 28)
    assert snapshot.last_cardio == date(2026, 8, 13)
    assert snapshot.week_sets == {"pull": 4, "push": 8, "legs": 9, "core": 6}


async def test_the_skipped_days_of_the_file_are_the_skipped_rows(
    db_session: AsyncSession,
) -> None:
    await import_training_state(db_session, state_text())

    skipped = {
        row.day_date
        for row in await training_crud.list_training_days(db_session)
        if row.skipped
    }

    assert skipped == {date(2026, 8, 14), date(2026, 8, 29), date(2026, 8, 30)}


async def test_the_stale_counter_of_the_file_is_not_carried_over(
    db_session: AsyncSession,
) -> None:
    # Файл говорит `skipped_days: 0` при пропусках 29 и 30 августа подряд. Это и
    # есть болезнь свёрнутой таблицы: счётчик поддерживался руками и разошёлся с
    # собственными ключами. Значение выводится, а не переносится.
    await import_training_state(db_session, state_text())
    row, snapshot = await training_crud.recompute_state(db_session, date(2026, 8, 30))

    assert snapshot.skipped_days == 2
    assert row.skipped_days == 2


async def test_the_open_complaint_lands_once(db_session: AsyncSession) -> None:
    await import_training_state(db_session, state_text())
    await import_training_state(db_session, state_text())

    complaints = await training_crud.list_complaints(db_session)
    assert len(complaints) == 1
    assert complaints[0].area == "левое плечо"
    assert complaints[0].status == COMPLAINT_OPEN
    assert complaints[0].opened_on == date(2026, 8, 10)


async def test_the_records_land_with_their_targets(db_session: AsyncSession) -> None:
    await import_training_state(db_session, state_text())

    records = {
        row.exercise: row for row in await training_crud.list_records(db_session)
    }

    assert records["pullups"].sets == "9/10/5/3"
    assert records["pullups"].target == "4x8 RIR 1-2"
    assert records["pullups"].achieved_on == date(2026, 8, 10)
    assert records["pushups"].best_plain == 50
    assert records["pushups"].variant == "на кулаках с паузой"


async def test_the_authored_progression_is_read(db_session: AsyncSession) -> None:
    await import_training_state(db_session, state_text())
    row = await training_crud.get_state(db_session)

    assert row is not None
    assert row.progression_stage["pull"].startswith("объём 4x6-8")


async def test_a_second_run_adds_nothing(db_session: AsyncSession) -> None:
    first = await import_training_state(db_session, state_text())
    second = await import_training_state(db_session, state_text())

    assert first.complaints == 1
    assert second.complaints == 0
    assert second.records == 0
    assert len(await training_crud.list_records(db_session)) == 2


async def test_the_cli_import_reads_the_file(
    db_session: AsyncSession, root: Path
) -> None:
    # Тот же файл через CLI из `#89`: тренировка приезжает вместе с планами,
    # а не отдельной командой.
    report = await import_root(db_session, root)

    assert report.training_written is True
    assert report.training_days > 0
    assert report.training_complaints == 1
    assert report.training_records == 2


async def test_the_second_cli_run_leaves_the_file_alone(
    db_session: AsyncSession, root: Path
) -> None:
    await import_root(db_session, root)
    again = await import_root(db_session, root)

    assert again.training_unchanged is True
    assert again.training_written is False
