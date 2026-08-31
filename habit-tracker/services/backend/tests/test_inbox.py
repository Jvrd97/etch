# [review:need-review] PHASE-03/97
# summary: tests for the inbox contour — a second poll of an unchanged workspace adds nothing, a changed task updates its row instead of doubling it, the local date comes from `app.core.daytime` and not from arithmetic of its own, a disabled source refuses without touching the network, a source with no adapter says so, the range limit matches table and health, and no table of the contour carries a column for a body

import hashlib
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import inbox as inbox_crud
from app.models.inbox import InboundSignal, SignalSource

INBOX_URL = "/api/v1/inbox"

# Задача личного воркспейса, как её отдаёт ClickUp. Полей у него больше; здесь
# те, что контур читает, — остальные адаптер и не смотрит.
TASK = {
    "id": "86cb3xtv5",
    "name": "Починить сквозной flow покупки",
    "url": "https://app.clickup.com/t/86cb3xtv5",
    "date_updated": "1788199200000",
    "status": {"status": "in progress"},
    "list": {"id": "901523757764", "name": "Backend"},
}


def clickup_transport(
    tasks: list[dict[str, Any]], calls: list[httpx.Request] | None = None
) -> httpx.MockTransport:
    """
    ClickUp, которого нет.

    Адаптер тестируется на транспорте, а не на сети: тест, ходящий наружу,
    краснеет от чужого релиза и от отсутствия интернета — и в обоих случаях
    рассказывает не про наш код.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        return httpx.Response(200, json={"tasks": tasks})

    return httpx.MockTransport(handler)


@pytest_asyncio.fixture
async def personal_source(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[SignalSource, None]:
    """
    Личный ClickUp, включённый и с токеном в окружении.

    Токен фиктивный и живёт только в этом процессе: адаптер читает его из
    окружения по имени из `credential_ref`, и подменять надо ровно окружение —
    иначе тест проверял бы не тот путь, которым ходит прод.
    """
    monkeypatch.setenv("CLICKUP_PERSONAL_TOKEN", "pk_test_not_a_real_token")
    await inbox_crud.seed_sources(db_session)
    source = await inbox_crud.get_source_by_name(db_session, "clickup", "personal")
    assert source is not None
    source.is_active = True
    await db_session.commit()
    await db_session.refresh(source)
    yield source


async def test_a_poll_stores_the_task_with_a_link_back(
    db_session: AsyncSession, personal_source: SignalSource
) -> None:
    """Первый прогон: задача видна, и по ссылке из неё возвращаются в ClickUp."""
    stored = await inbox_crud.poll_source(
        db_session, personal_source, transport=clickup_transport([TASK])
    )

    assert stored.ingested == 1
    signals = (await db_session.execute(select(InboundSignal))).scalars().all()
    assert len(signals) == 1
    assert signals[0].external_id == TASK["id"]
    assert signals[0].title == TASK["name"]
    assert signals[0].external_url == TASK["url"]


async def test_a_second_poll_of_an_unchanged_workspace_adds_nothing(
    db_session: AsyncSession, personal_source: SignalSource
) -> None:
    """
    Приёмка дедупликации (ADR-0016, D5).

    Естественный ключ плюс `ON CONFLICT DO UPDATE`: повторно увиденная задача
    обновляет снимок, а не плодит строку.
    """
    await inbox_crud.poll_source(
        db_session, personal_source, transport=clickup_transport([TASK])
    )
    second = await inbox_crud.poll_source(
        db_session, personal_source, transport=clickup_transport([TASK])
    )

    assert second.ingested == 0
    assert second.updated == 1
    signals = (await db_session.execute(select(InboundSignal))).scalars().all()
    assert len(signals) == 1


async def test_a_changed_task_updates_its_row_rather_than_doubling_it(
    db_session: AsyncSession, personal_source: SignalSource
) -> None:
    await inbox_crud.poll_source(
        db_session, personal_source, transport=clickup_transport([TASK])
    )
    renamed = {**TASK, "name": "Починить flow покупки — и письмо с QR"}

    await inbox_crud.poll_source(
        db_session, personal_source, transport=clickup_transport([renamed])
    )

    signals = (await db_session.execute(select(InboundSignal))).scalars().all()
    assert len(signals) == 1
    assert signals[0].title == renamed["name"]
    # Хеш содержимого — ответ на «изменилось ли», не хранящий содержимого.
    assert signals[0].content_hash != hashlib.sha256(TASK["name"].encode()).hexdigest()


async def test_the_local_date_comes_from_the_day_boundary_not_from_the_calendar(
    db_session: AsyncSession, personal_source: SignalSource
) -> None:
    """
    Задача, обновлённая в 00:30, принадлежит предыдущему дню.

    День идёт с 04:00, и это знает единственная функция `app.core.daytime`.
    Своей арифметики поясов в контуре нет — прямой урок personal-os, где коммит
    в 00:01 приписался новому дню.
    """
    from app.core.daytime import local_date

    at = datetime(2026, 9, 1, 0, 30, tzinfo=timezone.utc)
    late = {**TASK, "date_updated": str(int(at.timestamp() * 1000))}

    await inbox_crud.poll_source(
        db_session, personal_source, transport=clickup_transport([late])
    )

    signal = (await db_session.execute(select(InboundSignal))).scalars().one()
    assert signal.local_date == local_date(at)


async def test_a_disabled_source_refuses_and_does_not_touch_the_network(
    db_session: AsyncSession,
) -> None:
    """Выключенный источник — это выключенный источник, а не медленный."""
    await inbox_crud.seed_sources(db_session)
    source = await inbox_crud.get_source_by_name(db_session, "clickup", "personal")
    assert source is not None
    assert source.is_active is False

    calls: list[httpx.Request] = []
    with pytest.raises(inbox_crud.PollRefused) as error:
        await inbox_crud.poll_source(
            db_session, source, transport=clickup_transport([TASK], calls)
        )

    assert error.value.code == "source_disabled"
    assert calls == []


async def test_a_source_without_an_adapter_says_so_and_does_not_touch_the_network(
    db_session: AsyncSession,
) -> None:
    """
    Заготовка не притворяется рабочим источником.

    `clickup/alvion`, Gmail и Telegram стоят в справочнике ради экранного
    состояния «не подключён» и отказа обратной записи, но адаптеров у них нет.
    """
    await inbox_crud.seed_sources(db_session)
    source = await inbox_crud.get_source_by_name(db_session, "gmail", "personal")
    assert source is not None
    source.is_active = True
    await db_session.commit()

    calls: list[httpx.Request] = []
    with pytest.raises(inbox_crud.PollRefused) as error:
        await inbox_crud.poll_source(
            db_session, source, transport=clickup_transport([TASK], calls)
        )

    assert error.value.code == "no_adapter"
    assert calls == []


async def test_no_table_of_the_contour_has_a_column_for_a_body() -> None:
    """
    Приватность выражена отсутствием колонок (D2), и это проверяется, а не
    обещается: колонка под тело письма делает из бэкапа Postgres копию личной
    переписки.
    """
    from app.models.inbox import Commitment, SignalMirrorOp, SignalScope

    forbidden = {"body", "text_body", "content", "message", "snippet", "attachments"}
    for model in (SignalSource, SignalScope, InboundSignal, SignalMirrorOp):
        names = {column.name for column in model.__table__.columns}
        assert not (names & forbidden), f"{model.__tablename__}: {names & forbidden}"

    # У `commitments` колонка `text` есть, и это не тело: там живёт формулировка
    # обязательства, которую человек принял, — до 500 символов по ADR-0016 D3.
    assert "text" in {column.name for column in Commitment.__table__.columns}


async def test_the_seed_of_the_revision_and_of_the_module_do_not_drift() -> None:
    """
    Сид живёт дважды: в ревизии для рабочей базы и в модуле для тестовой.

    Тест сравнивает оба списка — иначе расхождение всплывёт на проде, где
    ревизия уже применена, а модуль говорит другое.
    """
    import importlib.util
    from pathlib import Path

    path = next(Path("alembic/versions").glob("*c5e7a9b1d3f6_inbound_signal_tables.py"))
    spec = importlib.util.spec_from_file_location("revision_under_test", path)
    assert spec is not None and spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)

    assert revision.SEED_SOURCES == inbox_crud.SEED_SOURCES


async def test_the_feed_shows_new_signals_newest_first(
    client: AsyncClient, db_session: AsyncSession, personal_source: SignalSource
) -> None:
    older = {**TASK, "id": "older", "date_updated": "1788100000000"}
    await inbox_crud.poll_source(
        db_session, personal_source, transport=clickup_transport([TASK, older])
    )

    response = await client.get(f"{INBOX_URL}/signals")

    assert response.status_code == 200
    body = response.json()
    assert [one["external_id"] for one in body] == [TASK["id"], "older"]


async def test_a_range_longer_than_a_year_is_refused_like_table_and_health(
    client: AsyncClient,
) -> None:
    response = await client.get(
        f"{INBOX_URL}/signals",
        params={"date_from": "2025-01-01", "date_to": "2026-12-31"},
    )

    assert response.status_code == 422
