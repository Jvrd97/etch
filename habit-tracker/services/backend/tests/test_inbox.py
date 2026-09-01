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
    monkeypatch.setenv("CLICKUP_PERSONAL_TEAM_ID", "90152350557")
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


async def test_the_workspace_id_travels_in_the_path_not_the_account_name(
    db_session: AsyncSession, personal_source: SignalSource
) -> None:
    """
    ClickUp адресует воркспейс числовым id.

    `account` в справочнике — это «личный» против «рабочего», человеческое
    различение; подставленное в путь, оно даёт 404 на первом же живом прогоне.
    Тест смотрит на URL запроса, потому что мок ответит на любой.
    """
    calls: list[httpx.Request] = []
    await inbox_crud.poll_source(
        db_session, personal_source, transport=clickup_transport([TASK], calls)
    )

    assert len(calls) == 1
    assert "/team/90152350557/task" in str(calls[0].url)


async def test_a_source_without_a_workspace_id_refuses_before_the_network(
    db_session: AsyncSession,
    personal_source: SignalSource,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CLICKUP_PERSONAL_TEAM_ID", raising=False)

    calls: list[httpx.Request] = []
    with pytest.raises(inbox_crud.PollRefused) as error:
        await inbox_crud.poll_source(
            db_session, personal_source, transport=clickup_transport([TASK], calls)
        )

    assert error.value.code == "no_workspace"
    assert calls == []


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


class TestCredentialsInTheRow:
    """
    Учётные данные задаются на сервере, а не переменной окружения.

    Первый срез назвал секрет именем env-переменной, и подключение второго
    воркспейса стоило захода на VPS с пересборкой контейнера.
    """

    async def test_a_saved_secret_is_not_readable_in_the_row(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """
        В базе лежит шифротекст.

        Цена названа в ADR: дамп `deploy/backup.sh` кладётся файлом на диск VPS,
        и открытый токен в нём означал бы, что укравший дамп получил и доступ.
        """
        await inbox_crud.seed_sources(db_session)
        source = await inbox_crud.get_source_by_name(db_session, "clickup", "personal")
        assert source is not None

        response = await client.put(
            f"{INBOX_URL}/sources/{source.id}/credentials",
            json={"secret": "pk_86cb_secret_value", "settings": {"team_id": "9015"}},
        )

        assert response.status_code == 200
        await db_session.refresh(source)
        assert source.secret_ciphertext is not None
        assert "pk_86cb_secret_value" not in source.secret_ciphertext
        assert source.settings["team_id"] == "9015"

    async def test_the_secret_never_leaves_the_server(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Наружу уходит «задан» — не значение и не его длина."""
        await inbox_crud.seed_sources(db_session)
        source = await inbox_crud.get_source_by_name(db_session, "clickup", "personal")
        assert source is not None
        await client.put(
            f"{INBOX_URL}/sources/{source.id}/credentials",
            json={"secret": "pk_86cb_secret_value", "settings": {"team_id": "9015"}},
        )

        listing = await client.get(f"{INBOX_URL}/sources")

        assert listing.status_code == 200
        body = listing.text
        assert "pk_86cb_secret_value" not in body
        row = next(one for one in listing.json() if one["id"] == source.id)
        assert row["has_secret"] is True
        assert "secret" not in row and "secret_ciphertext" not in row

    async def test_the_adapter_prefers_the_stored_secret_over_the_environment(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Введённое на сервере важнее окружения.

        Иначе смена токена через интерфейс молча ничего не меняла бы на машине,
        где старый токен остался в `.env`.
        """
        monkeypatch.setenv("CLICKUP_PERSONAL_TOKEN", "token_from_env")
        monkeypatch.setenv("CLICKUP_PERSONAL_TEAM_ID", "team_from_env")
        await inbox_crud.seed_sources(db_session)
        source = await inbox_crud.get_source_by_name(db_session, "clickup", "personal")
        assert source is not None
        await inbox_crud.set_credentials(
            db_session, source, secret="token_from_row", settings={"team_id": "9099"}
        )
        source.is_active = True
        await db_session.commit()

        calls: list[httpx.Request] = []
        await inbox_crud.poll_source(
            db_session, source, transport=clickup_transport([TASK], calls)
        )

        assert calls[0].headers["Authorization"] == "token_from_row"
        assert "/team/9099/task" in str(calls[0].url)

    async def test_the_environment_still_works_when_nothing_was_entered(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Живой прод с токеном в окружении не ломается появлением хранилища."""
        monkeypatch.setenv("CLICKUP_PERSONAL_TOKEN", "token_from_env")
        monkeypatch.setenv("CLICKUP_PERSONAL_TEAM_ID", "team_from_env")
        await inbox_crud.seed_sources(db_session)
        source = await inbox_crud.get_source_by_name(db_session, "clickup", "personal")
        assert source is not None
        source.is_active = True
        await db_session.commit()

        calls: list[httpx.Request] = []
        await inbox_crud.poll_source(
            db_session, source, transport=clickup_transport([TASK], calls)
        )

        assert calls[0].headers["Authorization"] == "token_from_env"


class TestTheWorkingWorkspace:
    """Рабочий ClickUp читается тем же адаптером — и остаётся read-only."""

    async def test_alvion_is_read_by_the_same_adapter(
        self, db_session: AsyncSession
    ) -> None:
        """
        Второй воркспейс — это данные, а не код.

        Адаптер выбирается по провайдеру: два аккаунта одного ClickUp
        различаются токеном и id воркспейса, а не веткой в коде.
        """
        await inbox_crud.seed_sources(db_session)
        source = await inbox_crud.get_source_by_name(db_session, "clickup", "alvion")
        assert source is not None
        await inbox_crud.set_credentials(
            db_session, source, secret="pk_alvion", settings={"team_id": "9016"}
        )
        source.is_active = True
        await db_session.commit()

        calls: list[httpx.Request] = []
        outcome = await inbox_crud.poll_source(
            db_session, source, transport=clickup_transport([TASK], calls)
        )

        assert outcome.ingested == 1
        assert "/team/9016/task" in str(calls[0].url)

    async def test_alvion_stays_read_only(self, db_session: AsyncSession) -> None:
        """
        Обратная запись — только личный воркспейс (ADR-0016, D7).

        В Alvion статус задачи что-то значит для команды, и закрывать её из
        трекера нельзя, даже когда токен позволяет.
        """
        await inbox_crud.seed_sources(db_session)
        source = await inbox_crud.get_source_by_name(db_session, "clickup", "alvion")
        assert source is not None
        assert source.direction == "read"
        assert inbox_crud.may_write_back(source) is False

        personal = await inbox_crud.get_source_by_name(
            db_session, "clickup", "personal"
        )
        assert personal is not None
        assert inbox_crud.may_write_back(personal) is True


def test_migrations_are_not_excluded_from_the_image() -> None:
    """
    Ревизии обязаны попадать в образ бэкенда.

    Строка `alembic/versions/*.py` стояла в `.dockerignore` с бутстрапа и не
    мешала ровно до тех пор, пока прод монтировал `./services/backend:/app`
    поверх образа: alembic читал ревизии с диска хоста. Как только dev-маунты
    убрали и контейнер стал жить своим образом, `alembic upgrade head` перестал
    находить ревизию, на которой стоит база, и выкат встал на миграции.

    Тест дешёвый и стоит здесь, потому что цена ошибки — остановленный выкат,
    а заметить её иначе можно только на проде.
    """
    from pathlib import Path

    lines = [
        line.strip()
        for line in Path(".dockerignore").read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    offenders = [
        line for line in lines if "alembic" in line and not line.startswith("!")
    ]
    assert offenders == [], (
        f".dockerignore исключает миграции из образа: {offenders}. "
        "Контейнер живёт образом, и alembic внутри него не найдёт ревизий."
    )


class TestProbe:
    """
    Проба источника: показать, что видно снаружи, и не тронуть ничего внутри.

    Отдельная операция, а не «poll, только покажи». Опрос отвечает числами и
    двигает состояние — курсор, `last_polled_at`, строки сигналов; после него
    «работает ли ключ» уже не спросишь тем же способом, потому что второй опрос
    честно вернёт ноль нового. Проба отвечает списком и не пишет ни строки,
    поэтому её можно нажать дважды подряд и оба раза увидеть одно и то же.
    """

    async def test_the_probe_shows_the_tasks_it_can_see(
        self, personal_source: SignalSource
    ) -> None:
        items = await inbox_crud.probe_source(
            personal_source, transport=clickup_transport([TASK])
        )
        assert [one.external_id for one in items] == [TASK["id"]]
        assert items[0].title == TASK["name"]
        assert items[0].external_url == TASK["url"]

    async def test_the_probe_writes_nothing_at_all(
        self, db_session: AsyncSession, personal_source: SignalSource
    ) -> None:
        """
        Ни сигналов, ни курсора, ни отметки о чтении.

        Проба — это вопрос «а видно ли», и ответ на него не должен менять того,
        что увидит следующий настоящий опрос. Сдвинутый пробой курсор украл бы
        у опроса ровно те задачи, которые проба показала человеку.
        """
        await inbox_crud.probe_source(
            personal_source, transport=clickup_transport([TASK])
        )

        signals = await db_session.execute(select(InboundSignal))
        assert signals.scalars().all() == []
        await db_session.refresh(personal_source)
        assert personal_source.cursor == {}
        assert personal_source.last_polled_at is None

    async def test_the_probe_ignores_the_cursor_and_asks_for_everything(
        self, db_session: AsyncSession, personal_source: SignalSource
    ) -> None:
        """
        Смысл кнопки — «покажи всё», а не «покажи новое с прошлого раза».

        У источника, который уже читали, курсор отсекает всё старое, и проба
        показала бы пустой список на прекрасно работающем ключе. Это худший из
        возможных ответов диагностики: он выглядит как поломка.
        """
        personal_source.cursor = {"updated_ms": 1788199200000}
        await db_session.commit()
        calls: list[httpx.Request] = []

        await inbox_crud.probe_source(
            personal_source, transport=clickup_transport([TASK], calls)
        )

        assert "date_updated_gt" not in calls[0].url.params

    async def test_a_disabled_source_is_refused_without_touching_the_network(
        self, db_session: AsyncSession, personal_source: SignalSource
    ) -> None:
        """«Выключен» означает, что наружу не ушло ни одного запроса, — и здесь тоже."""
        personal_source.is_active = False
        await db_session.commit()
        calls: list[httpx.Request] = []

        with pytest.raises(inbox_crud.PollRefused) as refusal:
            await inbox_crud.probe_source(
                personal_source, transport=clickup_transport([TASK], calls)
            )

        assert refusal.value.code == "source_disabled"
        assert calls == []

    async def test_the_handle_answers_with_the_list(
        self,
        client: AsyncClient,
        personal_source: SignalSource,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            inbox_crud,
            "ADAPTERS",
            {"clickup": lambda source, transport, *, full=False: _one_task()},
        )

        response = await client.post(f"{INBOX_URL}/sources/{personal_source.id}/probe")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["count"] == 1
        assert body["items"][0]["external_id"] == TASK["id"]


async def _one_task() -> list[inbox_crud.ExternalItem]:
    """Один разобранный элемент — то, что вернул бы адаптер на живом ключе."""
    return [
        inbox_crud.ExternalItem(
            external_id=str(TASK["id"]),
            title=str(TASK["name"]),
            external_url=str(TASK["url"]),
            occurred_at=datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc),
            content_hash="0" * 8,
        )
    ]
