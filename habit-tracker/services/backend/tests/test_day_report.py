"""
Отчёт дня строкой базы: ревизии, хэш и отчёт каждого источника о себе (`#145`).

Каждый пункт Acceptance тикета здесь словами тикета: отчёт собирается без
подпроцессов и без чтения файлов; пересборка на неизменившихся данных даёт тот
же `content_hash`; правка заметки «как прошло» даёт новую ревизию; старая
ревизия читается ровно такой, какой была записана; `sources` объясняет пустой
источник; отчёт дня, закрытого одним касанием, несёт признак `review_skipped`; и
ни один логгер нового кода не принимает текста дня.

Тесты гоняются поверх настоящей базы и без единого мока источников: «сборка
целиком» — это и есть предмет проверки.
"""

# [review:need-review] PHASE-03/145
# summary: tests of the day report as rows — immutability of a revision, the hash that recognises unchanged data, the new revision an edited note produces, the sources that explain their own emptiness, the report built by the 15:40 touch in the same transaction, and the grep that keeps the text of the day out of the logs
import re
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.daytime import today_local
from app.crud import day as day_crud
from app.day import report as report_service
from app.models.day_report import TRIGGER_API, TRIGGER_CLOSE, DayReport

DAY_URL = "/api/v1/day"

# Сегодня по границе дня канона: отметки ставятся только в открытое окно.
REPORT_DAY = today_local()
DAY_PATH = f"{DAY_URL}/{REPORT_DAY.isoformat()}"
PLAN_URL = f"{DAY_PATH}/plan"
REPORT_URL = f"{DAY_PATH}/report"


@pytest.fixture(autouse=True)
async def seeded_rules(
    db_session: AsyncSession, seeded_goal: int
) -> AsyncGenerator[None, None]:
    """Таблица правил и цель квартала, на которую ссылаются задачи плана."""
    await day_crud.seed_rules(db_session)
    yield


def task(code: str, window: str = "09:00-10:00", **overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "kind": "task",
        "code": code,
        "text_md": f"Задача {code}",
        "window": window,
        "done_criterion": "письмо отправлено",
        "quarter_goal_id": 1,
    }
    item.update(overrides)
    return item


def document(*items: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": f"План {REPORT_DAY.isoformat()}",
        "sections": [{"kind": "work", "title": "Работа", "items": list(items)}],
    }


async def post_plan(client: AsyncClient, *items: dict[str, Any]) -> dict[str, Any]:
    response = await client.post(PLAN_URL, json=document(*items))
    assert response.status_code == 201, response.text
    return dict(response.json())


def first_item(plan: dict[str, Any]) -> dict[str, Any]:
    return dict(plan["sections"][0]["items"][0])


async def build(client: AsyncClient, **params: Any) -> dict[str, Any]:
    response = await client.post(REPORT_URL, params=params)
    assert response.status_code == 200, response.text
    return dict(response.json())


async def read(client: AsyncClient, **params: Any) -> dict[str, Any]:
    response = await client.get(REPORT_URL, params=params)
    assert response.status_code == 200, response.text
    return dict(response.json())


async def rows(session: AsyncSession) -> list[DayReport]:
    result = await session.execute(select(DayReport).order_by(DayReport.revision))
    return list(result.scalars().all())


async def test_the_report_is_built_from_rows_alone(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """
    Сборка идёт на голой базе: ни подпроцесса, ни файла.

    Тест ничего не готовит на диске и не поднимает git — он просто зовёт сборку.
    Прошёл — значит, у отчёта других источников нет.
    """
    built = await build(client)

    assert built["revision"] == 0
    assert built["trigger"] == TRIGGER_API
    assert REPORT_DAY.isoformat() in built["content_md"]
    assert set(built["sources"]) == set(report_service.SOURCE_KEYS)
    assert len(await rows(db_session)) == 1


async def test_the_source_module_starts_no_subprocess_and_opens_no_file() -> None:
    """
    Отчёт не имеет права звать внешнюю команду или читать файл.

    Грепом по исходнику, а не моком: мок ловит один путь, а запрет — про весь
    модуль, включая тот путь, который допишут завтра.
    """
    source = Path(report_service.__file__).read_text(encoding="utf-8")

    for forbidden in ("subprocess", "os.system", "Popen", "open(", "read_text"):
        assert forbidden not in source, forbidden


async def test_no_logger_of_the_report_ever_sees_the_text_of_the_day(
    client: AsyncClient,
) -> None:
    """
    Ни один `logger.*` нового кода не принимает текста отчёта, пункта или заметки.

    Задача бывает названа по диагнозу, а отчёт целиком состоит из таких строк.
    Проверка грепом, потому что дисциплина здесь не работает.
    """
    source = Path(report_service.__file__).read_text(encoding="utf-8")

    calls = re.findall(r"logger\.\w+\((.*?)\)", source, flags=re.DOTALL)

    assert calls == []
    assert "logging" not in source


async def test_the_same_data_rebuilds_to_the_same_hash_and_no_new_revision(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Пересборка на неизменившихся данных узнаёт себя и не плодит ревизий."""
    plan = await post_plan(client, task("W1"))
    first = await build(client)

    second = await build(client)

    assert second["content_hash"] == first["content_hash"]
    assert second["revision"] == first["revision"]
    assert second["built_at"] == first["built_at"]
    assert [row.revision for row in await rows(db_session)] == [0]
    assert plan["sections"][0]["items"][0]["code"] == "W1"


async def test_an_edited_note_gives_a_new_revision_and_a_new_hash(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Правка заметки «как прошло» меняет текст, а значит и хэш, а значит и ревизию."""
    plan = await post_plan(client, task("W1"))
    item_id = first_item(plan)["id"]
    first = await build(client)

    marked = await client.put(
        f"{DAY_PATH}/marks/{item_id}",
        json={"state": "done", "note": "ушло два часа вместо одного"},
    )
    assert marked.status_code == 200, marked.text
    second = await build(client)

    assert second["revision"] == 1
    assert second["content_hash"] != first["content_hash"]
    assert "ушло два часа вместо одного" in second["content_md"]
    assert [row.revision for row in await rows(db_session)] == [0, 1]


async def test_an_old_revision_reads_exactly_as_it_was_written(
    client: AsyncClient,
) -> None:
    """Старая ревизия не меняется ни от одной пересборки — ни текстом, ни хэшем."""
    plan = await post_plan(client, task("W1"))
    zero = await build(client)

    item_id = first_item(plan)["id"]
    await client.put(
        f"{DAY_PATH}/marks/{item_id}", json={"state": "done", "note": "сделал"}
    )
    await build(client)
    await client.put(f"{DAY_PATH}/notebook", json={"content": "второй заход"})
    await build(client)

    stored = await read(client, revision=0)
    assert stored["content_md"] == zero["content_md"]
    assert stored["content_hash"] == zero["content_hash"]
    assert stored["built_at"] == zero["built_at"]
    assert stored["revisions"] == [0, 1, 2]


async def test_an_empty_source_says_why_it_is_empty(client: AsyncClient) -> None:
    """
    Пустой источник объясняет себя, а не молчит.

    Отчёт беднее прежнего `.report.md` ровно на коммиты, и это написано в
    `sources`, а не оставлено читателю на догадку.
    """
    built = await build(client)

    sources = built["sources"]
    assert sources["signals"]["available"] is False
    assert sources["signals"]["count"] == 0
    assert "контур не подключён" in sources["signals"]["note"]
    assert sources["notebook"]["count"] == 0
    assert sources["notebook"]["note"] != ""


async def test_a_source_that_gave_rows_explains_nothing(client: AsyncClient) -> None:
    """Объяснение обязательно там, где записей нет, и лишнее там, где они есть."""
    plan = await post_plan(client, task("W1"))
    item_id = first_item(plan)["id"]
    await client.put(
        f"{DAY_PATH}/marks/{item_id}", json={"state": "done", "note": "готово"}
    )

    built = await build(client)

    assert built["sources"]["marks"]["count"] == 1
    assert built["sources"]["marks"]["note"] == ""
    assert built["sources"]["notes"]["count"] == 1
    assert built["sources"]["notes"]["note"] == ""


async def test_a_day_with_no_marks_at_all_still_builds(client: AsyncClient) -> None:
    """Отчёт дня, на котором ничего не отмечали, — это отчёт, а не отказ."""
    built = await build(client)

    assert built["sources"]["marks"]["count"] == 0
    assert built["sources"]["marks"]["note"] != ""
    assert "Отметки" in built["content_md"]


async def test_the_review_touch_builds_the_report_in_the_same_transaction(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """
    Касание 15:40 собирает отчёт само, поводом `close`.

    Отчёт, собранный отдельной ручкой секундой позже, описывал бы уже другой
    день, а не тот, факт по которому только что записан.
    """
    await post_plan(client, task("W1"))

    reviewed = await client.post(f"{DAY_PATH}/close/review", json={"work_minutes": 400})

    assert reviewed.status_code == 200, reviewed.text
    stored = await rows(db_session)
    assert [row.trigger for row in stored] == [TRIGGER_CLOSE]


async def test_a_day_closed_in_one_touch_carries_the_sign_in_its_report(
    client: AsyncClient,
) -> None:
    """`review_skipped` виден в отчёте дня, у которого первого касания не было."""
    await post_plan(client, task("W1"))

    closed = await client.post(f"{DAY_PATH}/close/final", json={"body_md": "закрыл"})
    built = await build(client)

    assert closed.status_code == 200, closed.text
    assert "ревью 15:40 не было" in built["content_md"]


async def test_a_day_that_had_its_review_says_nothing_of_the_kind(
    client: AsyncClient,
) -> None:
    """Признак пропущенного ревью не появляется на дне, у которого ревью было."""
    await post_plan(client, task("W1"))
    await client.post(f"{DAY_PATH}/close/review", json={"work_minutes": 400})

    await client.post(f"{DAY_PATH}/close/final", json={"body_md": "закрыл"})
    built = await build(client)

    assert "ревью 15:40 не было" not in built["content_md"]


async def test_the_report_of_a_day_nobody_built_is_a_404(client: AsyncClient) -> None:
    """«Отчёта нет» и «отчёт пуст» ведут к разным действиям, поэтому это 404."""
    missing = await client.get(REPORT_URL)
    unknown = await client.post(REPORT_URL, params={"trigger": "неведомо"})

    assert missing.status_code == 404
    assert unknown.status_code == 422


async def test_a_revision_that_was_never_written_is_a_404(client: AsyncClient) -> None:
    await build(client)

    missing = await client.get(REPORT_URL, params={"revision": 7})

    assert missing.status_code == 404
