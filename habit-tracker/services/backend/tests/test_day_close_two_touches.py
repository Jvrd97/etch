"""
Закрытие дня в два касания: стадия, идемпотентность и перезакрытие.

Около 15:40 закрывается рабочая часть — факт по задачам и рабочие минуты;
вечером якоря и вердикт. До `#143` это было одно событие, и день, где ревью в
15:40 не случилось, ничем не отличался от дня, где оно было.

Тесты идут поверх реальной сессии БД, а не поверх моков: предмет проверки —
unique-ключи, `CHECK` на стадию и upsert одной строки, и мок здесь проверял бы
собственную выдумку.
"""

# [review:need-review] PHASE-03/143
# summary: API-тесты двух касаний — повтор с тем же ключом ничего не пишет, другой ключ перезакрывает без второй строки, день без касания 15:40 несёт review_skipped, стадия reviewed держит вердикт пустым, вердикт в теле даёт 422, закрытие вчера двигает стрик сегодня, а записка переопределения переживает перезакрытие
from collections.abc import AsyncGenerator
from datetime import date, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import day as day_crud
from app.day.evaluate import REASON_NOT_CLOSED, VERDICT_WON
from app.models.mark import MARK_DONE
from app.models.summary import STAGE_CLOSED, STAGE_OPEN, STAGE_REVIEWED, DaySummary

DAY_URL = "/api/v1/day"

# Понедельник и вторник под нынешним каноном. Даты фиксированы, а не отсчитаны
# от сегодня: стрик после выигранного понедельника равен 1, и то же утверждение
# в воскресенье равнялось бы нулю.
FIRST_DAY = date(2026, 8, 24)
SECOND_DAY = FIRST_DAY + timedelta(days=1)


@pytest.fixture(autouse=True)
async def seeded_rules(
    db_session: AsyncSession, seeded_goal: int
) -> AsyncGenerator[None, None]:
    """Канон дня в таблице — `create_all` сидов не знает."""
    await day_crud.seed_rules(db_session)
    await day_crud.list_rules(db_session)
    yield


def task(code: str, window: str = "09:00-10:00") -> dict[str, Any]:
    return {
        "kind": "task",
        "code": code,
        "text_md": f"Задача {code}",
        "window": window,
        "done_criterion": "письмо отправлено",
        "quarter_goal_id": 1,
    }


def anchor(text: str) -> dict[str, Any]:
    return {"kind": "anchor", "text_md": text}


async def post_plan(
    client: AsyncClient, on: date, *items: dict[str, Any]
) -> list[dict[str, Any]]:
    response = await client.post(
        f"{DAY_URL}/{on.isoformat()}/plan",
        json={"sections": [{"kind": "work", "title": "День", "items": list(items)}]},
    )
    assert response.status_code == 201, response.text
    return list(response.json()["sections"][0]["items"])


async def a_won_day(client: AsyncClient, on: date = FIRST_DAY) -> None:
    """Одна задача и один якорь, оба закрыты: день, который выигран."""
    items = await post_plan(client, on, task("W1"), anchor("Подъём 06:00"))
    for item in items:
        response = await client.put(
            f"{DAY_URL}/{on.isoformat()}/marks/{item['id']}", json={"state": MARK_DONE}
        )
        assert response.status_code == 200, response.text


def _headers(key: str | None) -> dict[str, str]:
    return {} if key is None else {"Idempotency-Key": key}


async def review(
    client: AsyncClient, on: date, *, key: str | None = None, **body: Any
) -> dict[str, Any]:
    """Касание 15:40; ответ отдаётся, статус проверяется здесь же."""
    response = await client.post(
        f"{DAY_URL}/{on.isoformat()}/close/review", json=body, headers=_headers(key)
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


async def final(
    client: AsyncClient, on: date, *, key: str | None = None, **body: Any
) -> dict[str, Any]:
    """Вечернее касание."""
    response = await client.post(
        f"{DAY_URL}/{on.isoformat()}/close/final", json=body, headers=_headers(key)
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


async def summary_of(client: AsyncClient, on: date) -> dict[str, Any]:
    response = await client.get(f"{DAY_URL}/{on.isoformat()}")
    assert response.status_code == 200, response.text
    return dict(response.json()["summary"])


async def rows_for(db: AsyncSession, on: date) -> int:
    """Сколько строк итога лежит на эту дату. Ответ обязан быть 0 или 1."""
    result = await db.execute(
        select(func.count()).select_from(DaySummary).where(DaySummary.day_date == on)
    )
    return int(result.scalar_one())


async def stored_row(db: AsyncSession, on: date) -> DaySummary:
    result = await db.execute(select(DaySummary).where(DaySummary.day_date == on))
    return result.scalar_one()


# --- две стадии ------------------------------------------------------------


async def test_the_day_starts_open_with_no_row_at_all(client: AsyncClient) -> None:
    """`open` — это отсутствие строки, а не третье слово в базе."""
    await post_plan(client, FIRST_DAY, task("W1"))

    live = await summary_of(client, FIRST_DAY)

    assert live["stage"] == STAGE_OPEN
    assert live["closed"] is False
    assert live["reviewed_at"] is None
    assert live["review_skipped"] is False


async def test_the_1540_touch_records_the_work_without_a_verdict(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """«День со стадией `reviewed` показывает "вердикт будет вечером"»."""
    await a_won_day(client)

    touched = await review(client, FIRST_DAY, work_minutes=300, body_md="пока ровно")

    assert touched["stage"] == STAGE_REVIEWED
    assert touched["closed"] is False
    assert touched["verdict"] is None
    assert touched["verdict_reason"] == REASON_NOT_CLOSED
    assert touched["reviewed_at"] is not None
    assert touched["body_md"] == "пока ровно"
    assert await rows_for(db_session, FIRST_DAY) == 1


async def test_the_evening_touch_closes_the_day_the_review_started(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await a_won_day(client)
    await review(client, FIRST_DAY, work_minutes=300)

    closed = await final(client, FIRST_DAY, body_md="день кончился")

    assert closed["stage"] == STAGE_CLOSED
    assert closed["closed"] is True
    assert closed["verdict"] == VERDICT_WON
    assert closed["streak_after"] == 1
    assert closed["review_skipped"] is False
    assert await rows_for(db_session, FIRST_DAY) == 1


async def test_the_evening_touch_keeps_what_the_review_wrote(
    client: AsyncClient,
) -> None:
    """`null` в теле — «не трогать»: вечер не обязан повторять цифру 15:40."""
    await a_won_day(client)
    await review(client, FIRST_DAY, work_minutes=300, body_md="пока ровно")

    closed = await final(client, FIRST_DAY)

    assert closed["work_minutes"] == 300
    assert closed["body_md"] == "пока ровно"


async def test_a_mark_put_after_1540_still_shows_before_the_evening(
    client: AsyncClient,
) -> None:
    """Полузакрытый день считается живьём, а не счётчиками из 15:40."""
    items = await post_plan(client, FIRST_DAY, task("W1"), task("W2", "10:00-11:00"))
    await review(client, FIRST_DAY, work_minutes=300)

    response = await client.put(
        f"{DAY_URL}/{FIRST_DAY.isoformat()}/marks/{items[0]['id']}",
        json={"state": MARK_DONE},
    )
    assert response.status_code == 200, response.text

    live = await summary_of(client, FIRST_DAY)
    assert (live["tasks_done"], live["tasks_total"]) == (1, 2)
    assert live["stage"] == STAGE_REVIEWED


# --- пропуск первого касания ------------------------------------------------


async def test_a_day_closed_in_one_touch_says_the_review_was_skipped(
    client: AsyncClient,
) -> None:
    """«Стадия `open → closed`, признак `review_skipped` виден в разборе»."""
    await a_won_day(client)

    closed = await final(client, FIRST_DAY, work_minutes=400)

    assert closed["stage"] == STAGE_CLOSED
    assert closed["review_skipped"] is True
    assert closed["reviewed_at"] is None
    assert closed["verdict"] == VERDICT_WON

    # И тот же признак виден на следующем чтении дня, а не только в ответе.
    assert (await summary_of(client, FIRST_DAY))["review_skipped"] is True


async def test_a_day_that_had_its_review_does_not_claim_it_was_skipped(
    client: AsyncClient,
) -> None:
    await a_won_day(client)
    await review(client, FIRST_DAY, work_minutes=300)
    await final(client, FIRST_DAY)

    assert (await summary_of(client, FIRST_DAY))["review_skipped"] is False


# --- идемпотентность --------------------------------------------------------


async def test_the_same_key_twice_writes_nothing_and_moves_no_timestamp(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """«Повтор отдаёт 200 и ту же строку; отметки времени не сдвигаются»."""
    await a_won_day(client)
    first = await final(client, FIRST_DAY, key="evening-1", work_minutes=400)
    written_at = (await stored_row(db_session, FIRST_DAY)).updated_at

    again = await final(client, FIRST_DAY, key="evening-1", work_minutes=999)

    assert again == first
    assert again["work_minutes"] == 400
    assert (await stored_row(db_session, FIRST_DAY)).updated_at == written_at
    assert await rows_for(db_session, FIRST_DAY) == 1


async def test_another_key_recloses_the_day_and_leaves_one_row(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """«Тот же запрос с другим ключом пересчитывает вердикт; строка одна»."""
    await a_won_day(client)
    await final(client, FIRST_DAY, key="evening-1", work_minutes=400)

    again = await final(client, FIRST_DAY, key="evening-2", work_minutes=420)

    assert again["work_minutes"] == 420
    assert again["verdict"] == VERDICT_WON
    assert again["streak_after"] == 1
    assert await rows_for(db_session, FIRST_DAY) == 1


async def test_the_review_key_is_separate_from_the_final_one(
    client: AsyncClient,
) -> None:
    """Один ключ на касание: ключ ревью не закрывает вечернее касание."""
    await a_won_day(client)
    await review(client, FIRST_DAY, key="same-key", work_minutes=300)

    closed = await final(client, FIRST_DAY, key="same-key")

    assert closed["stage"] == STAGE_CLOSED
    assert closed["verdict"] == VERDICT_WON


async def test_a_key_spent_on_another_date_is_a_conflict(
    client: AsyncClient,
) -> None:
    """Ответить чужим днём было бы враньём, записать — сломать обещание ключа."""
    await a_won_day(client)
    await final(client, FIRST_DAY, key="evening-1", work_minutes=400)

    response = await client.post(
        f"{DAY_URL}/{SECOND_DAY.isoformat()}/close/final",
        json={},
        headers={"Idempotency-Key": "evening-1"},
    )

    assert response.status_code == 409, response.text
    assert FIRST_DAY.isoformat() in response.json()["detail"]


async def test_a_repeated_review_key_does_not_move_the_review_stamp(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await a_won_day(client)
    await review(client, FIRST_DAY, key="review-1", work_minutes=300)
    stamped = (await stored_row(db_session, FIRST_DAY)).reviewed_at

    again = await review(client, FIRST_DAY, key="review-1", work_minutes=999)

    assert again["work_minutes"] == 300
    assert (await stored_row(db_session, FIRST_DAY)).reviewed_at == stamped


async def test_a_review_after_the_evening_does_not_reopen_the_day(
    client: AsyncClient,
) -> None:
    """Ревью, пришедшее после закрытия, уточняет цифры, а не отменяет вердикт."""
    await a_won_day(client)
    await final(client, FIRST_DAY, work_minutes=400)

    late = await review(client, FIRST_DAY, work_minutes=430)

    assert late["stage"] == STAGE_CLOSED
    assert late["closed"] is True
    assert late["verdict"] == VERDICT_WON
    assert late["work_minutes"] == 430


# --- что касание не принимает ----------------------------------------------


async def test_a_verdict_in_the_body_is_refused_rather_than_ignored(
    client: AsyncClient,
) -> None:
    """«Тело с полем `verdict` вердикт не меняет — поля нет в схеме приёма»."""
    await a_won_day(client)

    response = await client.post(
        f"{DAY_URL}/{FIRST_DAY.isoformat()}/close/final",
        json={"verdict": "lost"},
    )

    assert response.status_code == 422, response.text
    assert (await summary_of(client, FIRST_DAY))["verdict"] is None


async def test_the_review_touch_refuses_a_verdict_too(client: AsyncClient) -> None:
    await a_won_day(client)

    response = await client.post(
        f"{DAY_URL}/{FIRST_DAY.isoformat()}/close/review",
        json={"verdict": "won"},
    )

    assert response.status_code == 422, response.text


# --- задним числом и переопределение ---------------------------------------


async def test_closing_yesterday_moves_todays_streak(client: AsyncClient) -> None:
    """«Закрытие вчерашнего дня пересчитывает стрик сегодняшнего»."""
    await a_won_day(client, FIRST_DAY)
    await a_won_day(client, SECOND_DAY)

    later = await final(client, SECOND_DAY, work_minutes=400)
    assert later["streak_after"] == 1

    await final(client, FIRST_DAY, work_minutes=400)

    assert (await summary_of(client, SECOND_DAY))["streak_after"] == 2


async def test_the_override_note_survives_a_reclose(client: AsyncClient) -> None:
    """«Ручное переопределение продолжает работать и после перезакрытия»."""
    items = await post_plan(client, FIRST_DAY, task("W1"))
    del items
    overridden = await final(
        client,
        FIRST_DAY,
        key="evening-1",
        verdict_override=True,
        verdict_override_note="задача сделана, отметить забыл",
    )
    assert overridden["verdict"] == VERDICT_WON

    again = await final(client, FIRST_DAY, key="evening-2", work_minutes=400)

    assert again["verdict_override"] is True
    assert again["verdict_override_note"] == "задача сделана, отметить забыл"
    assert again["verdict"] == VERDICT_WON


async def test_the_deprecated_close_is_the_evening_touch(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Старая ручка — синоним `final`, а не второй способ закрыть день."""
    await a_won_day(client)

    response = await client.post(
        f"{DAY_URL}/{FIRST_DAY.isoformat()}/close",
        json={"work_minutes": 400},
        headers={"Idempotency-Key": "evening-1"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["stage"] == STAGE_CLOSED

    # И ключ у неё тот же самый: повтор через новое имя ничего не пишет.
    written_at = (await stored_row(db_session, FIRST_DAY)).updated_at
    await final(client, FIRST_DAY, key="evening-1", work_minutes=999)
    assert (await stored_row(db_session, FIRST_DAY)).updated_at == written_at
