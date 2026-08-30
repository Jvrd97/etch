# [review:need-review] PHASE-03/117
# summary: deleting a conversation leaves nothing behind — no row in any of the four chat tables and no .jsonl session file — while a missing file, a forged session id and an applied plan's receipt each keep their own behaviour; plus the usage rollup checked against SELECT sum over chat_messages
"""
Удаление разговора и свёртка расхода.

Проверяется не «ручка ответила 204», а то, что после неё **ничего не осталось**:
строк во всех четырёх таблицах и файла сессии на диске. Обратная сторона того же
утверждения — чего трогать нельзя: файла вне каталога конфигурации и записей,
сделанных применением плана.

Файловая часть гоняется на временном каталоге, подставленном в
`settings.CHAT_CLAUDE_CONFIG_DIR`: настоящий `/data/claude-chat` в тесте не
существует, а мокать `unlink` значило бы проверять мок, а не удаление.
"""

from collections.abc import AsyncGenerator
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.crud import chat as chat_crud
from app.llm.chat.session_files import (
    OUTCOME_ABSENT,
    OUTCOME_NO_SESSION,
    OUTCOME_OUTSIDE_CONFIG_DIR,
    OUTCOME_REMOVED,
    project_dir_name,
    remove_session_file,
    session_file_path,
)
from app.models.applied_daily_summary import AppliedDailySummary
from app.models.chat import (
    MESSAGE_ROLE_ASSISTANT,
    MESSAGE_ROLE_USER,
    PLAN_STATUS_APPLIED,
    ChatConversation,
    ChatMessage,
    ChatPlan,
    ChatRetrieval,
)

# Рабочий каталог разговора. Тот же, что в настройках по умолчанию: имя каталога
# проекта считается по нему, и подменять его нечем.
CWD = "/data/claude-chat/workspace"

# Идентификатор сессии CLI — тридцать шесть символов, как в колонке.
SESSION_ID = "11111111-2222-3333-4444-555555555555"

DAY = date(2026, 8, 30)


@pytest.fixture
async def config_dir(tmp_path: Path) -> AsyncGenerator[Path, None]:
    """Каталог конфигурации чата на время одного теста."""
    original = settings.CHAT_CLAUDE_CONFIG_DIR
    settings.CHAT_CLAUDE_CONFIG_DIR = str(tmp_path / "claude-chat")
    yield Path(settings.CHAT_CLAUDE_CONFIG_DIR)
    settings.CHAT_CLAUDE_CONFIG_DIR = original


def write_session_file(config_dir: Path, session_id: str = SESSION_ID) -> Path:
    """Положить файл сессии туда, где его ищет CLI, и вернуть путь."""
    path = session_file_path(config_dir=str(config_dir), cwd=CWD, session_id=session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"type":"user"}\n', encoding="utf-8")
    return path


async def seed_conversation(
    db: AsyncSession,
    *,
    session_id: str | None = SESSION_ID,
    cwd: str | None = CWD,
) -> ChatConversation:
    """
    Разговор со всем, что каскад обязан унести: сообщение, план и выборка.

    Строки пишутся руками, а не ручками `#114`/`#115`: тех ручек ещё нет, а
    проверять надо каскад, а не путь, которым строка попала в таблицу.
    """
    conversation = ChatConversation(
        started_on=DAY,
        cli_session_id=session_id,
        cli_cwd=cwd,
    )
    db.add(conversation)
    await db.flush()

    question = ChatMessage(
        conversation_id=conversation.id,
        seq=1,
        role=MESSAGE_ROLE_USER,
        content="Что сегодня по плану?",
    )
    answer = ChatMessage(
        conversation_id=conversation.id,
        seq=2,
        role=MESSAGE_ROLE_ASSISTANT,
        content="Три задачи и тренировка.",
        input_tokens=1200,
        output_tokens=300,
        cache_read_tokens=900,
        latency_ms=4000,
    )
    db.add_all([question, answer])
    await db.flush()

    db.add(
        ChatPlan(
            message_id=answer.id,
            entry_date=DAY,
            plan={"sections": []},
        )
    )
    db.add(
        ChatRetrieval(
            message_id=answer.id,
            query_name="day_card",
            params={"date": DAY.isoformat()},
            row_count=1,
            chars=120,
        )
    )
    await db.flush()
    return conversation


async def count_rows(
    db: AsyncSession, conversation_id: int
) -> tuple[int, int, int, int]:
    """Сколько строк осталось в каждой из четырёх таблиц по этому разговору."""
    conversations = await db.scalar(
        select(func.count(ChatConversation.id)).where(
            ChatConversation.id == conversation_id
        )
    )
    messages = await db.scalar(
        select(func.count(ChatMessage.id)).where(
            ChatMessage.conversation_id == conversation_id
        )
    )
    plans = await db.scalar(select(func.count(ChatPlan.id)))
    retrievals = await db.scalar(select(func.count(ChatRetrieval.id)))
    return (conversations or 0, messages or 0, plans or 0, retrievals or 0)


# --------------------------------------------------------------------------
# Путь файла сессии — без базы и без ручек
# --------------------------------------------------------------------------


def test_the_project_directory_is_the_cwd_with_every_separator_flattened() -> None:
    assert project_dir_name("/data/claude-chat/workspace") == (
        "-data-claude-chat-workspace"
    )
    assert project_dir_name("/srv/habit_tracker.ai") == "-srv-habit-tracker-ai"


def test_the_session_file_sits_under_projects_named_by_the_cwd() -> None:
    path = session_file_path(config_dir="/cfg", cwd=CWD, session_id=SESSION_ID)
    assert path == Path(f"/cfg/projects/-data-claude-chat-workspace/{SESSION_ID}.jsonl")


def test_a_conversation_without_a_session_has_no_file_to_remove(
    config_dir: Path,
) -> None:
    assert (
        remove_session_file(config_dir=str(config_dir), cwd=CWD, session_id=None)
        == OUTCOME_NO_SESSION
    )
    assert (
        remove_session_file(config_dir=str(config_dir), cwd=None, session_id=SESSION_ID)
        == OUTCOME_NO_SESSION
    )


def test_the_file_at_the_computed_path_is_the_one_that_goes(
    config_dir: Path,
) -> None:
    written = write_session_file(config_dir)
    neighbour = write_session_file(config_dir, session_id="another-session")

    assert (
        remove_session_file(config_dir=str(config_dir), cwd=CWD, session_id=SESSION_ID)
        == OUTCOME_REMOVED
    )
    assert not written.exists()
    assert neighbour.exists()


def test_a_missing_file_is_absent_and_not_an_error(config_dir: Path) -> None:
    assert (
        remove_session_file(config_dir=str(config_dir), cwd=CWD, session_id=SESSION_ID)
        == OUTCOME_ABSENT
    )


def test_an_id_climbing_out_of_the_configuration_directory_removes_nothing(
    config_dir: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "keep-me.jsonl"
    outside.write_text("не трогать", encoding="utf-8")

    # `../../keep-me` из каталога проекта выводит ровно в `tmp_path`.
    forged = "../../../keep-me"
    assert (
        remove_session_file(config_dir=str(config_dir), cwd=CWD, session_id=forged)
        == OUTCOME_OUTSIDE_CONFIG_DIR
    )
    assert outside.exists()


def test_an_id_reaching_into_another_project_removes_nothing(
    config_dir: Path,
) -> None:
    neighbour = session_file_path(
        config_dir=str(config_dir), cwd="/data/claude-chat/other", session_id=SESSION_ID
    )
    neighbour.parent.mkdir(parents=True, exist_ok=True)
    neighbour.write_text("чужая сессия", encoding="utf-8")

    forged = f"../{project_dir_name('/data/claude-chat/other')}/{SESSION_ID}"
    assert (
        remove_session_file(config_dir=str(config_dir), cwd=CWD, session_id=forged)
        == OUTCOME_OUTSIDE_CONFIG_DIR
    )
    assert neighbour.exists()


# --------------------------------------------------------------------------
# DELETE /chat/conversations/{id}
# --------------------------------------------------------------------------


async def test_delete_empties_all_four_tables_and_takes_the_session_file(
    client: AsyncClient, db_session: AsyncSession, config_dir: Path
) -> None:
    conversation = await seed_conversation(db_session)
    await db_session.commit()
    session_file = write_session_file(config_dir)

    response = await client.delete(f"/api/v1/chat/conversations/{conversation.id}")

    assert response.status_code == 204
    assert await count_rows(db_session, conversation.id) == (0, 0, 0, 0)
    assert not session_file.exists()


async def test_a_conversation_that_never_had_a_session_file_deletes_cleanly(
    client: AsyncClient, db_session: AsyncSession, config_dir: Path
) -> None:
    conversation = await seed_conversation(db_session, session_id=None, cwd=None)
    await db_session.commit()

    response = await client.delete(f"/api/v1/chat/conversations/{conversation.id}")

    assert response.status_code == 204
    assert await count_rows(db_session, conversation.id) == (0, 0, 0, 0)


async def test_a_session_file_gone_from_disk_does_not_fail_the_delete(
    client: AsyncClient, db_session: AsyncSession, config_dir: Path
) -> None:
    """Том с сессиями пересоздан: строки в базе есть, файла нет."""
    conversation = await seed_conversation(db_session)
    await db_session.commit()

    response = await client.delete(f"/api/v1/chat/conversations/{conversation.id}")

    assert response.status_code == 204
    assert await count_rows(db_session, conversation.id) == (0, 0, 0, 0)


async def test_a_forged_session_id_deletes_the_rows_and_no_file_outside(
    client: AsyncClient, db_session: AsyncSession, config_dir: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "hostage.jsonl"
    outside.write_text("файл вне каталога конфигурации", encoding="utf-8")

    conversation = await seed_conversation(db_session, session_id="../../../hostage")
    await db_session.commit()

    response = await client.delete(f"/api/v1/chat/conversations/{conversation.id}")

    assert response.status_code == 204
    assert await count_rows(db_session, conversation.id) == (0, 0, 0, 0)
    assert outside.exists()


async def test_deleting_a_conversation_that_is_not_there_is_404(
    client: AsyncClient, db_session: AsyncSession, config_dir: Path
) -> None:
    response = await client.delete("/api/v1/chat/conversations/4242")
    assert response.status_code == 404


async def test_the_receipt_of_an_applied_plan_outlives_the_conversation(
    client: AsyncClient, db_session: AsyncSession, config_dir: Path
) -> None:
    """
    Удаление разговора стирает разговор, а не работу, сделанную по нему.

    Квитанция `applied_daily_summaries` — то, чем идемпотентность узнаёт
    повтор: сотри её вместе с разговором, и тот же ключ применится второй раз.
    """
    receipt = AppliedDailySummary(
        idempotency_key="key-of-an-applied-day",
        entry_date=DAY,
        entry_ids=[],
        journal_entry_id=None,
        metric_pairs=[],
    )
    db_session.add(receipt)
    await db_session.flush()

    conversation = await seed_conversation(db_session)
    plan = await db_session.scalar(select(ChatPlan))
    assert plan is not None
    plan.status = PLAN_STATUS_APPLIED
    plan.applied_summary_id = receipt.id
    plan.applied_at = datetime.now(timezone.utc)
    await db_session.commit()

    response = await client.delete(f"/api/v1/chat/conversations/{conversation.id}")

    assert response.status_code == 204
    assert await count_rows(db_session, conversation.id) == (0, 0, 0, 0)
    survivors = await db_session.scalars(select(AppliedDailySummary))
    assert [one.id for one in survivors] == [receipt.id]


async def test_a_neighbouring_conversation_is_untouched(
    client: AsyncClient, db_session: AsyncSession, config_dir: Path
) -> None:
    doomed = await seed_conversation(db_session)
    keeper = await seed_conversation(db_session, session_id=None, cwd=None)
    await db_session.commit()

    response = await client.delete(f"/api/v1/chat/conversations/{doomed.id}")

    assert response.status_code == 204
    kept = await db_session.scalar(
        select(func.count(ChatMessage.id)).where(
            ChatMessage.conversation_id == keeper.id
        )
    )
    assert kept == 2


# --------------------------------------------------------------------------
# Свёртка расхода
# --------------------------------------------------------------------------


async def test_the_rollup_matches_the_sum_over_chat_messages(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    conversation = await seed_conversation(db_session, session_id=None, cwd=None)
    await db_session.commit()

    response = await client.get(f"/api/v1/chat/conversations/{conversation.id}")
    assert response.status_code == 200
    usage = response.json()["usage"]

    totals = (
        await db_session.execute(
            select(
                func.coalesce(func.sum(ChatMessage.input_tokens), 0),
                func.coalesce(func.sum(ChatMessage.output_tokens), 0),
                func.coalesce(func.sum(ChatMessage.cache_read_tokens), 0),
            ).where(ChatMessage.conversation_id == conversation.id)
        )
    ).one()

    assert usage["input_tokens"] == totals[0]
    assert usage["output_tokens"] == totals[1]
    assert usage["cache_read_tokens"] == totals[2]
    assert usage["message_count"] == 2
    assert usage["latency_ms_median"] == 4000


async def test_the_feed_carries_the_same_rollup_as_the_detail(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    first = await seed_conversation(db_session, session_id=None, cwd=None)
    second = await seed_conversation(db_session, session_id=None, cwd=None)
    db_session.add(
        ChatMessage(
            conversation_id=second.id,
            seq=3,
            role=MESSAGE_ROLE_ASSISTANT,
            content="Ещё один ход.",
            input_tokens=100,
            output_tokens=50,
            cache_read_tokens=1100,
            latency_ms=2000,
        )
    )
    await db_session.commit()

    feed = (await client.get("/api/v1/chat/conversations")).json()
    by_id = {one["id"]: one["usage"] for one in feed}

    assert by_id[first.id]["input_tokens"] == 1200
    assert by_id[second.id]["input_tokens"] == 1300
    assert by_id[second.id]["cache_read_tokens"] == 2000
    # Медиана двух замеров — среднее между ними, а не первый попавшийся.
    assert by_id[second.id]["latency_ms_median"] == 3000

    detail = (await client.get(f"/api/v1/chat/conversations/{second.id}")).json()
    assert detail["usage"] == by_id[second.id]


async def test_a_conversation_without_messages_costs_zero(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    created = await client.post("/api/v1/chat/conversations", json={})
    assert created.status_code == 201
    assert created.json()["usage"] == {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "message_count": 0,
        "latency_ms_median": None,
    }

    detail = (
        await client.get(f"/api/v1/chat/conversations/{created.json()['id']}")
    ).json()
    assert detail["usage"]["message_count"] == 0
    assert detail["usage"]["latency_ms_median"] is None


async def test_a_turn_without_a_measured_latency_leaves_the_median_empty(
    db_session: AsyncSession,
) -> None:
    conversation = ChatConversation(started_on=DAY)
    db_session.add(conversation)
    await db_session.flush()
    db_session.add(
        ChatMessage(
            conversation_id=conversation.id,
            seq=1,
            role=MESSAGE_ROLE_USER,
            content="Реплика человека задержки не имеет.",
        )
    )
    await db_session.flush()

    usage = await chat_crud.usage_of(db_session, conversation.id)

    assert usage.message_count == 1
    assert usage.input_tokens == 0
    assert usage.latency_ms_median is None


async def test_the_rollup_of_an_unknown_conversation_is_the_empty_one(
    db_session: AsyncSession,
) -> None:
    assert await chat_crud.usage_of(db_session, 999) == chat_crud.EMPTY_USAGE
    assert await chat_crud.usage_by_conversation(db_session, []) == {}


def test_the_rollup_query_never_asks_for_the_message_text() -> None:
    """
    Ни один столбец свёртки не `content`.

    Проверяется по тому самому запросу, который выполняет `usage_by_conversation`,
    а не по чтению кода: свёртка едет в ленте, и `SELECT content` в ней означает
    весь текст всех разговоров через сеть ради трёх чисел в шапке.
    """
    sql = str(chat_crud.usage_statement([1, 2]))

    assert "content" not in sql
    assert "sum(chat_messages.input_tokens)" in sql
    assert "percentile_cont" in sql
