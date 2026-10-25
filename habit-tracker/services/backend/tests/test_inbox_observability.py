# [review:need-review] PHASE-03/105
# summary: tests for the observability of inbox sources — refusal codes fold into six stable classes, one failing source (unexpected exception, bad JSON, a database error while storing) does not cancel the others, a missing credentials file is `needs_login` with no adapter call, a source without an adapter is `not_implemented` with no network call, and no exception text carrying PII reaches `last_error_code`, the API or the log

import logging
from io import StringIO
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from httpx import AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import inbox as inbox_crud
from app.inbox import errors
from app.models.inbox import InboundSignal, SignalSource
from tests.conftest import test_engine

INBOX_URL = "/api/v1/inbox"

PERSONAL_TEAM = "9015"
ALVION_TEAM = "9016"

# Текст, которого в диагностике быть не должно: тема письма, адрес и имя чата.
LEAKY_TEXT = "Договор с ivan.petrov@example.com, чат «Мама», сумма 1 200 000"
LEAKY_FRAGMENTS = ("Договор", "ivan.petrov", "example.com", "Мама", "1 200 000")

MOMENT = datetime(2026, 10, 20, 9, 30, tzinfo=timezone.utc)


def task(task_id: str, name: str = "Починить покупку") -> dict[str, Any]:
    return {
        "id": task_id,
        "name": name,
        "url": f"https://app.clickup.com/t/{task_id}",
        "date_updated": str(int(MOMENT.timestamp() * 1000)),
        "status": {"status": "open"},
    }


Reply = Callable[[httpx.Request], httpx.Response]


def workspaces(
    by_team: dict[str, Reply], calls: list[httpx.Request] | None = None
) -> httpx.MockTransport:
    """
    ClickUp, которого нет, — по ответу на каждый воркспейс.

    Путь запроса `/api/v2/team/<id>/task`: id воркспейса — пятый сегмент. Один
    транспорт на все источники, потому что `refresh_stale` отдаёт его всем.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        team = request.url.path.split("/")[4]
        return by_team[team](request)

    return httpx.MockTransport(handler)


def tasks_reply(*tasks: dict[str, Any]) -> Reply:
    return lambda request: httpx.Response(200, json={"tasks": list(tasks)})


def status_reply(code: int, body: str = "") -> Reply:
    return lambda request: httpx.Response(code, content=body.encode())


class FakeAdapter:
    """Адаптер Telegram или Gmail, которого ещё нет: считает вызовы."""

    def __init__(
        self,
        items: list[inbox_crud.ExternalItem] | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.items = items or []
        self.error = error
        self.calls = 0

    async def __call__(
        self,
        source: SignalSource,
        transport: httpx.AsyncBaseTransport | None,
        *,
        full: bool = False,
    ) -> list[inbox_crud.ExternalItem]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.items


def one_item(external_id: str = "tg-1") -> inbox_crud.ExternalItem:
    return inbox_crud.ExternalItem(
        external_id=external_id,
        title=None,
        external_url=None,
        occurred_at=MOMENT,
        content_hash="h",
    )


async def make_source(
    db: AsyncSession,
    provider: str,
    account: str,
    *,
    secret: str | None = "pk_test",
    team: str | None = None,
) -> SignalSource:
    await inbox_crud.seed_sources(db)
    source = await inbox_crud.get_source_by_name(db, provider, account)
    assert source is not None
    settings = {"team_id": team} if team is not None else None
    await inbox_crud.set_credentials(db, source, secret=secret, settings=settings)
    source.is_active = True
    await db.commit()
    return source


@pytest.fixture
def session_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Файл сессии Telegram, на который указывает переменная источника."""
    path = tmp_path / "telethon.session"
    path.write_bytes(b"session")
    monkeypatch.setenv("TELEGRAM_SESSION_PATH", str(path))
    return path


@pytest.fixture
def fake_telegram(monkeypatch: pytest.MonkeyPatch) -> FakeAdapter:
    adapter = FakeAdapter(items=[one_item()])
    monkeypatch.setitem(inbox_crud.ADAPTERS, "telegram", adapter)
    return adapter


class TestClasses:
    """Шесть устойчивых классов вместо строки исключения."""

    @pytest.mark.parametrize(
        ("code", "expected"),
        [
            ("http_401", errors.ERROR_AUTH_EXPIRED),
            ("http_403", errors.ERROR_AUTH_EXPIRED),
            ("http_429", errors.ERROR_RATE_LIMITED),
            ("http_500", errors.ERROR_REMOTE),
            ("http_404", errors.ERROR_REMOTE),
            ("transport_failed", errors.ERROR_NETWORK),
            ("no_credentials", errors.ERROR_NEEDS_LOGIN),
            ("no_workspace", errors.ERROR_NEEDS_LOGIN),
            ("secret_unreadable", errors.ERROR_NEEDS_LOGIN),
            ("no_adapter", errors.ERROR_NOT_IMPLEMENTED),
            ("error_RuntimeError", errors.ERROR_REMOTE),
            ("something_new_we_never_saw", errors.ERROR_REMOTE),
        ],
    )
    def test_a_code_folds_into_its_class(self, code: str, expected: str) -> None:
        assert errors.class_of_code(code) == expected

    def test_a_switched_off_source_is_not_an_error(self) -> None:
        """«Выключен» — решение человека, а не поломка: класса у него нет."""
        assert errors.class_of_code("source_disabled") is None
        assert errors.class_of_code(None) is None

    def test_the_classes_are_exactly_the_six_of_the_ticket(self) -> None:
        assert set(errors.ERROR_CLASSES) == {
            "auth_expired",
            "needs_login",
            "rate_limited",
            "network",
            "remote_error",
            "not_implemented",
        }

    def test_an_unknown_exception_is_named_by_its_class_alone(self) -> None:
        """Класс исключения — не текст: имя типа, ни слова из сообщения."""
        code = errors.code_of_exception(RuntimeError(LEAKY_TEXT))

        assert code == "error_RuntimeError"
        assert not any(piece in code for piece in LEAKY_FRAGMENTS)

    def test_a_long_class_name_still_fits_the_column(self) -> None:
        huge = type("X" * 200, (Exception,), {})

        assert len(errors.code_of_exception(huge())) <= errors.ERROR_CODE_MAX_CHARS

    def test_known_failures_keep_the_code_the_screen_already_reads(self) -> None:
        assert (
            errors.code_of_exception(httpx.ConnectError("boom")) == "transport_failed"
        )
        assert errors.code_of_exception(httpx.ReadTimeout("slow")) == "transport_failed"
        assert (
            errors.code_of_exception(FileNotFoundError(LEAKY_TEXT)) == "no_credentials"
        )


class TestOneSourceDoesNotStopTheOthers:
    """Деградация по одному источнику вместо остановки всех."""

    async def test_a_source_answering_garbage_does_not_cancel_the_other_two(
        self,
        db_session: AsyncSession,
        session_file: Path,
        fake_telegram: FakeAdapter,
    ) -> None:
        """
        Первым идёт личный ClickUp — и он отвечает не JSON-ом.

        Раньше `response.json()` падал мимо `PollRefused`, и разговор о дне
        вместе с остальными двумя источниками уходил в исключение.
        """
        personal = await make_source(
            db_session, "clickup", "personal", team=PERSONAL_TEAM
        )
        alvion = await make_source(db_session, "clickup", "alvion", team=ALVION_TEAM)
        await make_source(db_session, "telegram", "personal", secret=None)
        transport = workspaces(
            {
                PERSONAL_TEAM: status_reply(200, f"<html>{LEAKY_TEXT}</html>"),
                ALVION_TEAM: tasks_reply(task("a-1")),
            }
        )

        codes = await inbox_crud.refresh_stale(db_session, transport=transport)

        assert codes == ["error_JSONDecodeError"]
        stored = {
            one.source_id
            for one in (await db_session.execute(select(InboundSignal))).scalars()
        }
        telegram = await inbox_crud.get_source_by_name(
            db_session, "telegram", "personal"
        )
        assert telegram is not None
        assert stored == {alvion.id, telegram.id}
        assert personal.last_polled_at is None
        assert alvion.last_error_code is None
        assert alvion.last_ingested == 1
        assert fake_telegram.calls == 1

    async def test_an_adapter_that_raises_is_recorded_and_the_loop_goes_on(
        self,
        db_session: AsyncSession,
        session_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Исключение адаптера Telegram не доходит до тех, кто стоит после него."""
        broken = FakeAdapter(error=RuntimeError(LEAKY_TEXT))
        monkeypatch.setitem(inbox_crud.ADAPTERS, "telegram", broken)
        personal = await make_source(
            db_session, "clickup", "personal", team=PERSONAL_TEAM
        )
        telegram = await make_source(db_session, "telegram", "personal", secret=None)
        transport = workspaces({PERSONAL_TEAM: tasks_reply(task("p-1"))})

        codes = await inbox_crud.refresh_stale(db_session, transport=transport)

        assert codes == ["error_RuntimeError"]
        assert personal.last_ingested == 1
        assert telegram.last_error_code == "error_RuntimeError"
        assert errors.class_of_code(telegram.last_error_code) == errors.ERROR_REMOTE

    async def test_a_database_error_while_storing_does_not_poison_the_session(
        self, db_session: AsyncSession
    ) -> None:
        """
        Сбой записи одного источника не ломает транзакцию следующего.

        Идентификатор длиннее колонки ломает вставку на стороне базы. Без
        точки сохранения сессия остаётся в состоянии «ждёт rollback», и второй
        источник падает уже не по своей вине.
        """
        personal = await make_source(
            db_session, "clickup", "personal", team=PERSONAL_TEAM
        )
        alvion = await make_source(db_session, "clickup", "alvion", team=ALVION_TEAM)
        transport = workspaces(
            {
                PERSONAL_TEAM: tasks_reply(task("x" * 400)),
                ALVION_TEAM: tasks_reply(task("a-1")),
            }
        )

        codes = await inbox_crud.refresh_stale(db_session, transport=transport)

        assert len(codes) == 1 and codes[0].startswith("error_")
        assert personal.last_polled_at is None
        assert personal.cursor == {}
        assert alvion.last_ingested == 1
        stored = (await db_session.execute(select(InboundSignal))).scalars().all()
        assert [one.external_id for one in stored] == ["a-1"]

    async def test_the_failed_run_keeps_the_time_of_the_last_good_one(
        self, db_session: AsyncSession
    ) -> None:
        """
        «Опрошен в» — время последнего успешного прогона, а не последней попытки.

        Пустая лента с вчерашним «опрошен» и ошибкой сегодня — это сломанный
        источник; пустая лента с сегодняшним «опрошен» — тихий день.
        """
        source = await make_source(
            db_session, "clickup", "personal", team=PERSONAL_TEAM
        )
        await inbox_crud.poll_source(
            db_session,
            source,
            transport=workspaces({PERSONAL_TEAM: tasks_reply(task("p-1"))}),
        )
        good_run = source.last_polled_at
        assert good_run is not None

        with pytest.raises(inbox_crud.PollRefused):
            await inbox_crud.poll_source(
                db_session,
                source,
                transport=workspaces({PERSONAL_TEAM: status_reply(401)}),
            )

        assert source.last_polled_at == good_run
        assert source.last_error_code == "http_401"
        assert source.last_error_at is not None

    async def test_a_good_run_after_a_bad_one_clears_the_error(
        self, db_session: AsyncSession
    ) -> None:
        source = await make_source(
            db_session, "clickup", "personal", team=PERSONAL_TEAM
        )
        with pytest.raises(inbox_crud.PollRefused):
            await inbox_crud.poll_source(
                db_session,
                source,
                transport=workspaces({PERSONAL_TEAM: status_reply(500)}),
            )

        await inbox_crud.poll_source(
            db_session,
            source,
            transport=workspaces({PERSONAL_TEAM: tasks_reply(task("p-1"))}),
        )

        assert source.last_error_code is None
        assert source.last_error_at is None
        assert source.last_ingested == 1


class TestMissingCredentialsFile:
    """Нет файла сессии — это «нужен вход», а не авария и не сетевой вызов."""

    async def test_a_deleted_session_file_is_needs_login_and_the_adapter_is_not_called(
        self,
        db_session: AsyncSession,
        session_file: Path,
        fake_telegram: FakeAdapter,
    ) -> None:
        personal = await make_source(
            db_session, "clickup", "personal", team=PERSONAL_TEAM
        )
        telegram = await make_source(db_session, "telegram", "personal", secret=None)
        session_file.unlink()
        transport = workspaces({PERSONAL_TEAM: tasks_reply(task("p-1"))})

        codes = await inbox_crud.refresh_stale(db_session, transport=transport)

        assert codes == ["no_credentials"]
        assert fake_telegram.calls == 0
        assert telegram.last_error_code == "no_credentials"
        assert (
            errors.class_of_code(telegram.last_error_code) == errors.ERROR_NEEDS_LOGIN
        )
        # Воркер жив, ClickUp в том же прогоне прочитан.
        assert personal.last_ingested == 1

    async def test_an_unset_path_is_the_same_state(
        self,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
        fake_telegram: FakeAdapter,
    ) -> None:
        monkeypatch.delenv("TELEGRAM_SESSION_PATH", raising=False)
        telegram = await make_source(db_session, "telegram", "personal", secret=None)

        codes = await inbox_crud.refresh_stale(db_session)

        assert codes == ["no_credentials"]
        assert fake_telegram.calls == 0
        assert telegram.last_error_code == "no_credentials"

    async def test_putting_the_file_back_heals_the_source(
        self,
        db_session: AsyncSession,
        session_file: Path,
        fake_telegram: FakeAdapter,
    ) -> None:
        """Вход вернули — следующий прогон читает и сам стирает «нужен вход»."""
        telegram = await make_source(db_session, "telegram", "personal", secret=None)
        session_file.rename(session_file.with_name("moved.session"))
        await inbox_crud.refresh_stale(db_session)
        assert telegram.last_error_code == "no_credentials"
        session_file.with_name("moved.session").rename(session_file)

        codes = await inbox_crud.refresh_stale(db_session)

        assert codes == []
        assert fake_telegram.calls == 1
        assert telegram.last_error_code is None
        assert telegram.last_ingested == 1

    async def test_a_deleted_file_surfaces_through_the_manual_button_with_the_same_class(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        session_file: Path,
        fake_telegram: FakeAdapter,
    ) -> None:
        telegram = await make_source(db_session, "telegram", "personal", secret=None)
        session_file.unlink()

        response = await client.post(f"{INBOX_URL}/sources/{telegram.id}/poll")

        assert response.status_code == 409
        assert response.json()["detail"]["error_class"] == "needs_login"
        listing = (await client.get(f"{INBOX_URL}/sources")).json()
        row = next(one for one in listing if one["id"] == telegram.id)
        assert row["last_error_class"] == "needs_login"
        assert fake_telegram.calls == 0


class TestSourceWithoutAnAdapter:
    """Заготовка не притворяется ни пустой, ни сломанной."""

    async def test_it_is_not_implemented_and_never_touches_the_network(
        self, db_session: AsyncSession
    ) -> None:
        gmail = await make_source(db_session, "gmail", "personal", secret=None)
        calls: list[httpx.Request] = []
        transport = workspaces({PERSONAL_TEAM: tasks_reply(task("p-1"))}, calls)

        codes = await inbox_crud.refresh_stale(db_session, transport=transport)

        assert codes == []
        assert calls == []
        assert gmail.last_error_code is None

        with pytest.raises(inbox_crud.PollRefused) as refusal:
            await inbox_crud.poll_source(db_session, gmail, transport=transport)
        assert refusal.value.code == "no_adapter"
        assert errors.class_of_code(refusal.value.code) == errors.ERROR_NOT_IMPLEMENTED
        assert calls == []

    async def test_the_directory_says_so(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await inbox_crud.seed_sources(db_session)

        listing = (await client.get(f"{INBOX_URL}/sources")).json()

        by_name = {f"{one['provider']}/{one['account']}": one for one in listing}
        assert by_name["clickup/personal"]["has_adapter"] is True
        assert by_name["clickup/alvion"]["has_adapter"] is True
        assert by_name["gmail/personal"]["has_adapter"] is False
        assert by_name["telegram/personal"]["has_adapter"] is False

    async def test_the_manual_button_answers_with_the_class_not_a_white_screen(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        gmail = await make_source(db_session, "gmail", "personal", secret=None)

        response = await client.post(f"{INBOX_URL}/sources/{gmail.id}/poll")

        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["code"] == "no_adapter"
        assert detail["error_class"] == "not_implemented"


class TestTheDirectoryShowsWhatBroke:
    async def test_the_screen_and_the_button_name_the_same_class(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        «Перечитать» на сломанном источнике — тот же класс, что на карточке.

        Истёкший токен Gmail или ClickUp выглядит одинаково: 401 от провайдера.
        """
        source = await make_source(
            db_session, "clickup", "personal", team=PERSONAL_TEAM
        )
        original = inbox_crud.poll_source
        expired = workspaces({PERSONAL_TEAM: status_reply(401, LEAKY_TEXT)})

        async def poll_through_fake_clickup(
            db: AsyncSession, one: SignalSource, **kwargs: Any
        ) -> inbox_crud.PollOutcome:
            return await original(db, one, transport=expired)

        monkeypatch.setattr(inbox_crud, "poll_source", poll_through_fake_clickup)

        response = await client.post(f"{INBOX_URL}/sources/{source.id}/poll")

        assert response.status_code == 409
        assert response.json()["detail"]["error_class"] == "auth_expired"
        row = next(
            one
            for one in (await client.get(f"{INBOX_URL}/sources")).json()
            if one["id"] == source.id
        )
        assert row["last_error_code"] == "http_401"
        assert row["last_error_class"] == "auth_expired"
        assert row["last_error_at"] is not None
        assert row["last_polled_at"] is None

    async def test_a_good_run_reports_its_count_and_the_cursor_moment(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        source = await make_source(
            db_session, "clickup", "personal", team=PERSONAL_TEAM
        )
        await inbox_crud.poll_source(
            db_session,
            source,
            transport=workspaces(
                {PERSONAL_TEAM: tasks_reply(task("p-1"), task("p-2"))}
            ),
        )

        row = next(
            one
            for one in (await client.get(f"{INBOX_URL}/sources")).json()
            if one["id"] == source.id
        )

        assert row["last_ingested"] == 2
        assert row["last_error_class"] is None
        assert row["last_polled_at"] is not None
        assert datetime.fromisoformat(row["cursor_at"].replace("Z", "+00:00")) == MOMENT

    async def test_a_source_nobody_read_has_no_cursor_and_no_count(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await inbox_crud.seed_sources(db_session)

        row = (await client.get(f"{INBOX_URL}/sources")).json()[0]

        assert row["cursor_at"] is None
        assert row["last_ingested"] is None
        assert row["last_error_at"] is None


class TestNoPersonalDataInTheDiagnostics:
    """`last_error` — это класс исключения и код ответа, ничего из содержимого."""

    async def test_an_exception_carrying_pii_leaves_no_trace(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        session_file: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setitem(
            inbox_crud.ADAPTERS, "telegram", FakeAdapter(error=ValueError(LEAKY_TEXT))
        )
        telegram = await make_source(db_session, "telegram", "personal", secret=None)

        with caplog.at_level(logging.DEBUG):
            response = await client.post(f"{INBOX_URL}/sources/{telegram.id}/poll")
            listing = await client.get(f"{INBOX_URL}/sources")

        assert response.status_code == 409
        await db_session.refresh(telegram)
        surfaces = [
            telegram.last_error_code or "",
            response.text,
            listing.text,
            caplog.text,
        ]
        for surface in surfaces:
            assert not any(piece in surface for piece in LEAKY_FRAGMENTS)
        assert telegram.last_error_code == "error_ValueError"

    async def test_a_provider_body_is_not_kept_either(
        self, db_session: AsyncSession
    ) -> None:
        """Тело ответа с названием задачи чужого воркспейса — тоже содержимое."""
        source = await make_source(
            db_session, "clickup", "personal", team=PERSONAL_TEAM
        )

        with pytest.raises(inbox_crud.PollRefused) as refusal:
            await inbox_crud.poll_source(
                db_session,
                source,
                transport=workspaces({PERSONAL_TEAM: status_reply(403, LEAKY_TEXT)}),
            )

        assert source.last_error_code == "http_403"
        assert not any(piece in refusal.value.message for piece in LEAKY_FRAGMENTS)

    async def test_the_probe_turns_an_unexpected_exception_into_a_refusal_too(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        session_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setitem(
            inbox_crud.ADAPTERS, "telegram", FakeAdapter(error=ValueError(LEAKY_TEXT))
        )
        telegram = await make_source(db_session, "telegram", "personal", secret=None)

        response = await client.post(f"{INBOX_URL}/sources/{telegram.id}/probe")

        assert response.status_code == 409
        assert response.json()["detail"]["error_class"] == "remote_error"
        assert not any(piece in response.text for piece in LEAKY_FRAGMENTS)
        await db_session.refresh(telegram)
        assert telegram.last_error_code is None  # проба ничего не пишет


@pytest.fixture
def statements() -> Iterator[list[str]]:
    """Все SQL-запросы, ушедшие в базу за время теста."""
    seen: list[str] = []

    def record(
        conn: Any, cursor: Any, statement: str, params: Any, context: Any, many: bool
    ) -> None:
        seen.append(statement)

    event.listen(test_engine.sync_engine, "before_cursor_execute", record)
    yield seen
    event.remove(test_engine.sync_engine, "before_cursor_execute", record)


class TestCostDoesNotGrowWithTheNumberOfSources:
    async def test_the_directory_is_one_query_however_many_sources_there_are(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        statements: list[str],
    ) -> None:
        """Справочник — один SELECT, а не по запросу на источник."""
        await inbox_crud.seed_sources(db_session)
        statements.clear()
        await client.get(f"{INBOX_URL}/sources")
        baseline = len(statements)

        for number in range(8):
            db_session.add(
                SignalSource(
                    provider="clickup",
                    account=f"extra-{number}",
                    is_active=False,
                    cursor={},
                )
            )
        await db_session.commit()
        statements.clear()
        await client.get(f"{INBOX_URL}/sources")

        assert len(statements) == baseline


OBSERVABILITY_REVISION = "h0d2f4a6c8e1"
OBSERVABILITY_PREVIOUS_REVISION = "a9c1e3f5b7d0"


def _migration_sql(revision_range: str, *, downgrade: bool) -> str:
    config = Config()
    config.set_main_option("script_location", "alembic")
    buffer = StringIO()
    config.output_buffer = buffer
    runner = command.downgrade if downgrade else command.upgrade
    runner(config, revision_range, sql=True)
    return buffer.getvalue().lower()


def test_the_observability_revision_is_reversible_and_keeps_one_head() -> None:
    """Две колонки добавляются и снимаются; цепочка по-прежнему с одной головой."""
    config = Config()
    config.set_main_option("script_location", "alembic")
    assert len(ScriptDirectory.from_config(config).get_heads()) == 1

    upgrade_sql = _migration_sql(
        f"{OBSERVABILITY_PREVIOUS_REVISION}:{OBSERVABILITY_REVISION}", downgrade=False
    )
    assert "add column last_error_at timestamp with time zone" in upgrade_sql
    assert "add column last_ingested integer" in upgrade_sql

    downgrade_sql = _migration_sql(
        f"{OBSERVABILITY_REVISION}:{OBSERVABILITY_PREVIOUS_REVISION}", downgrade=True
    )
    assert "drop column last_ingested" in downgrade_sql
    assert "drop column last_error_at" in downgrade_sql
