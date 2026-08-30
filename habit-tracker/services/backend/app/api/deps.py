# [review:need-review] PHASE-01/73-daily-summary-metrics-vertical, PHASE-03/111
# summary: shared FastAPI dependencies — the single LLM-client provider both LLM endpoints (and their tests) hang off, the chat transport beside it, and a session *factory* for the one endpoint that must not hold a pooled connection while a model is generating
"""
Общие зависимости FastAPI.

**Фабрика сессий отдельно от сессии.** `get_db` держит соединение из пула, пока
не закончится ответ. Для стрима это значит «все сто двадцать секунд генерации»,
и на двух воркерах разговор способен выесть пул. Поэтому ход чата берёт
`get_session_factory` и решает сам, когда открыть сессию и когда её отпустить:
контекст читается, сессия закрывается, ответ пишется новой. Это же закрывает
долг из `concern-charts-ai-followups.md`.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.llm.chat.client import ChatLLMClient, resolve_chat_client
from app.llm.client import LLMClient, resolve_llm_client

# Что раздаёт `get_session_factory`: вызов возвращает контекстный менеджер с
# сессией внутри. Тест подменяет фабрику на ту, что отдаёт свою сессию и не
# закрывает её.
SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


def get_llm_client() -> LLMClient | None:
    """
    LLM client dependency; None when no backend is available (the 503 case).

    One function rather than one per endpoint: FastAPI keys an override on the
    function object, so a second copy would mean a test that mocks the model for
    one endpoint still reaches the real backend from another.
    """
    return resolve_llm_client()


def get_chat_llm_client() -> ChatLLMClient | None:
    """
    Транспорт разговора; None — чат выключен (503).

    Клиент чата резолвится только здесь, как и одноходовой: бизнес-логика не
    зовёт LLM напрямую, и точка выбора бэкенда остаётся одна на эндпоинт.
    """
    return resolve_chat_client()


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Сессия на время блока; закрывается вместе с блоком, а не с ответом."""
    async with AsyncSessionLocal() as session:
        yield session


def get_session_factory() -> SessionFactory:
    """Фабрика сессий для эндпоинтов, которые управляют сессией сами."""
    return session_scope
