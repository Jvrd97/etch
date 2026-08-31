"""
Дни, которые не закрывали, и вердикты, которые нельзя пересчитывать (`#144`).

Два хвоста, которые перенос истории оставил. Первый: день без итога был
неотличим от проигранного — теперь он `stage='open'`, `verdict=NULL` и пустой
квадрат. Второй: перенесённый вердикт пересчитать нечем, поэтому любая ветка
пересчёта обязана его пропускать и сказать об этом вслух, а не молча оставить
прежнее число.

Тесты гоняются поверх настоящей базы: и идемпотентность прогона, и ветка
пропуска пересчёта — свойства строк, а не вызовов.
"""

# [review:need-review] PHASE-03/144
# summary: tests of the fourth state of a day and of the verdict that arrived as prose — the backfill that fills the calendar and writes nothing twice, the recompute that names the days it left alone, both touches refusing an imported day, the ambiguous prose that stays unjudged and is reported, the origin of the verdict on the wire, and the date-by-date reconciliation against the files
import shutil
from collections.abc import AsyncGenerator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import day as day_crud
from app.crud import summary as summary_crud
from app.day.evaluate import VERDICT_LOST
from app.imports.day_stage_backfill import _parse_args, backfill, verdicts_from_files
from app.imports.personal_os import import_root
from app.models.day import Day
from app.models.summary import (
    ORIGIN_COMPUTED,
    ORIGIN_MIGRATED_PROSE,
    ORIGIN_NONE,
    SOURCE_IMPORT,
    STAGE_OPEN,
    DaySummary,
)

FIXTURES = Path(__file__).parent / "fixtures" / "personal_os"

# Даты фикстуры, у которых итог есть. 20 августа — «Вне игры (выходной)»: проза
# есть, вердикта в ней нет.
LEGACY_SUMMARY = date(2026, 8, 14)
OFF_SUMMARY = date(2026, 8, 20)
LIVE_DAY = date(2026, 8, 28)

# День фикстуры, у которого плана нет и итога нет: ровно то состояние, ради
# которого тикет заведён.
NEVER_CLOSED = date(2026, 8, 26)


@pytest.fixture(autouse=True)
async def seeded_rules(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    """Таблица правил, как её видит мигрированная база; `create_all` без seed."""
    await day_crud.seed_rules(db_session)
    await day_crud.list_rules(db_session)
    yield


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """Копия репозитория-фикстуры: под корень никто не пишет."""
    copied = tmp_path / "personal-os"
    shutil.copytree(FIXTURES, copied)
    return copied


async def snapshot(session: AsyncSession) -> list[tuple[Any, ...]]:
    """Каждый итог значениями — вердикт, стадия, источник, счётчики, стрик."""
    result = await session.execute(select(DaySummary).order_by(DaySummary.day_date))
    return [
        (
            row.day_date,
            row.verdict,
            row.verdict_reason,
            row.stage,
            row.source,
            row.anchors_done,
            row.tasks_done,
            row.streak_after,
            row.body_md,
        )
        for row in result.scalars().all()
    ]


async def day_dates(session: AsyncSession) -> list[date]:
    result = await session.execute(select(Day.day_date).order_by(Day.day_date))
    return list(result.scalars().all())


async def test_a_day_nobody_closed_is_open_with_no_verdict(
    db_session: AsyncSession, client: AsyncClient, root: Path
) -> None:
    """
    Четвёртое состояние: день есть, итога нет, вердикта нет.

    До `#143` отсутствие итога было неотличимо от проигрыша — и в файлах, и на
    таймлайне. Здесь оно называется стадией.
    """
    await import_root(db_session, root)

    assert await summary_crud.get_summary(db_session, NEVER_CLOSED) is None
    response = await client.get(f"/api/v1/day/{NEVER_CLOSED.isoformat()}")

    assert response.status_code == 200
    summary = response.json()["summary"]
    assert summary["stage"] == STAGE_OPEN
    assert summary["verdict"] is None
    assert summary["closed"] is False
    assert summary["verdict_origin"] == ORIGIN_NONE


async def test_the_timeline_tells_an_unclosed_day_from_a_lost_one(
    db_session: AsyncSession, client: AsyncClient, root: Path
) -> None:
    """
    `GET /days` отдаёт три состояния, и происхождение вердикта рядом с ним.

    Пустой квадрат таймлайна — это `verdict: null`; серый — `lost`. Подпись «из
    записи» приезжает полем, а не вычисляется на экране по источнику, которого
    у экрана нет.
    """
    await import_root(db_session, root)

    response = await client.get(
        "/api/v1/days", params={"from": "2026-08-01", "to": "2026-08-31"}
    )

    assert response.status_code == 200
    by_date = {item["date"]: item for item in response.json()}
    assert by_date[NEVER_CLOSED.isoformat()]["verdict"] is None
    assert by_date[NEVER_CLOSED.isoformat()]["verdict_origin"] == ORIGIN_NONE
    assert by_date[LIVE_DAY.isoformat()]["verdict"] == VERDICT_LOST
    assert by_date[LIVE_DAY.isoformat()]["verdict_origin"] == ORIGIN_MIGRATED_PROSE
    # «Вне игры (выходной)»: проза есть, вердикта нет — и происхождения тоже.
    assert by_date[OFF_SUMMARY.isoformat()]["verdict"] is None
    assert by_date[OFF_SUMMARY.isoformat()]["verdict_origin"] == ORIGIN_NONE


async def test_the_recompute_names_the_days_it_left_alone(
    db_session: AsyncSession, root: Path
) -> None:
    """
    Пересчёт не молчит о пропуске: даты перенесённых вердиктов — в отчёте.

    Молчаливый пропуск неотличим от пересчёта, давшего то же число, а решения
    это разные.
    """
    await import_root(db_session, root)
    before = await snapshot(db_session)

    report = await summary_crud.recompute_history(db_session)

    assert set(report.kept_prose) == {LEGACY_SUMMARY, OFF_SUMMARY, LIVE_DAY}
    assert report.judged == []
    assert await snapshot(db_session) == before


async def test_closing_a_migrated_day_refuses_and_says_why(
    db_session: AsyncSession, client: AsyncClient, root: Path
) -> None:
    """Перезакрытие перенесённого дня вердикт не переписывает, и ответ объясняет отказ."""
    await import_root(db_session, root)
    before = await snapshot(db_session)

    refused = await client.post(
        f"/api/v1/day/{LIVE_DAY.isoformat()}/close/final",
        json={"body_md": "перезакрываю"},
    )
    reviewed = await client.post(
        f"/api/v1/day/{LIVE_DAY.isoformat()}/close/review",
        json={"work_minutes": 500},
    )

    assert refused.status_code == 409
    assert "прозой" in refused.json()["detail"]
    assert reviewed.status_code == 409
    assert await snapshot(db_session) == before


async def test_the_import_reports_a_summary_whose_prose_names_no_verdict(
    db_session: AsyncSession, root: Path
) -> None:
    """
    День, чья проза читается неоднозначно, попадает в отчёт и остаётся без вердикта.

    «Вне игры (выходной)» — не «да» и не «нет». Угадать его значило бы выдумать
    половину истории.
    """
    report = await import_root(db_session, root)

    assert report.unjudged == [OFF_SUMMARY]
    stored = await summary_crud.get_summary(db_session, OFF_SUMMARY)
    assert stored is not None
    assert stored.verdict is None
    assert stored.source == SOURCE_IMPORT


async def test_the_backfill_fills_the_calendar_and_the_second_run_writes_nothing(
    db_session: AsyncSession, root: Path
) -> None:
    """
    Прогон доводит календарь до состояния без дыр и повторно не пишет ничего.

    Дыру делает сам тест: строка дня удаляется после импорта, как её и не было
    бы в базе, перенесённой до `#143`.
    """
    await import_root(db_session, root)
    # Удаление строкой SQL, а не через ORM: строка дня в сессии уже загружена
    # импортом, и `db.delete` потянул бы за собой каскад, которого прогон не
    # видит. `__table__.delete()` mypy не типизирует — отсюда ignore.
    await db_session.execute(
        Day.__table__.delete().where(Day.day_date == NEVER_CLOSED)  # type: ignore[arg-type]
    )
    await db_session.flush()
    verdicts_before = await snapshot(db_session)

    first = await backfill(db_session)
    second = await backfill(db_session)

    assert NEVER_CLOSED in first.days_created
    assert second.days_created == []
    assert NEVER_CLOSED in await day_dates(db_session)
    # Ни один вердикт не тронут — ни первым прогоном, ни вторым.
    assert await snapshot(db_session) == verdicts_before


async def test_the_backfill_sorts_the_days_into_open_migrated_and_unjudged(
    db_session: AsyncSession, root: Path
) -> None:
    """Отчёт прогона называет каждое из четырёх состояний, а не только счётчики."""
    await import_root(db_session, root)

    report = await backfill(db_session)

    assert NEVER_CLOSED in report.open_days
    assert report.migrated_lost == [LEGACY_SUMMARY, LIVE_DAY]
    assert report.migrated_won == []
    assert report.unjudged == [OFF_SUMMARY]
    assert report.mismatches == []


async def test_the_backfill_reconciles_the_verdicts_with_the_files_by_date(
    db_session: AsyncSession, root: Path
) -> None:
    """
    Сверка по датам, а не на глаз: что говорят `summaries/**`, то и в базе.

    Расхождение — список дат, а не «похоже, всё сошлось»: одинаковое число
    жёлтых квадратов сходится и тогда, когда две даты поменялись местами.
    """
    await import_root(db_session, root)

    report = await backfill(db_session, root=root)

    assert report.checked_against_files is True
    assert report.mismatches == []
    assert verdicts_from_files(root) == {
        LEGACY_SUMMARY: VERDICT_LOST,
        OFF_SUMMARY: None,
        LIVE_DAY: VERDICT_LOST,
    }


async def test_the_reconciliation_shows_the_date_where_the_two_disagree(
    db_session: AsyncSession, root: Path
) -> None:
    """Вердикт, разошедшийся с файлом, называется датой и обеими сторонами."""
    await import_root(db_session, root)
    stored = await summary_crud.get_summary(db_session, LIVE_DAY)
    assert stored is not None
    stored.verdict = None
    await db_session.flush()

    report = await backfill(db_session, root=root)

    assert [one.day_date for one in report.mismatches] == [LIVE_DAY]
    assert report.mismatches[0].in_files == VERDICT_LOST
    assert report.mismatches[0].in_db is None


async def test_a_day_closed_here_is_computed_not_migrated(
    db_session: AsyncSession, client: AsyncClient
) -> None:
    """Вердикт, посчитанный здесь, подписан «вычислен» — иначе подпись бесполезна."""
    on = date(2026, 8, 29)
    await day_crud.ensure_day(db_session, on)

    closed = await client.post(
        f"/api/v1/day/{on.isoformat()}/close/final", json={"body_md": "закрыл"}
    )

    assert closed.status_code == 200
    assert closed.json()["verdict"] is not None
    assert closed.json()["verdict_origin"] == ORIGIN_COMPUTED


def test_the_backfill_writes_nothing_unless_it_is_told_to() -> None:
    """
    Умолчание — сухой прогон: команда без флагов считает и печатает, не записывая.

    Проверяется на разборе аргументов, потому что запись здесь ровно одна ветка:
    `--apply` коммитит, всё остальное откатывает транзакцию.
    """
    assert _parse_args([]).apply is False
    assert _parse_args(["--dry-run"]).apply is False
    assert _parse_args(["--apply"]).apply is True
    assert _parse_args([]).root is None
