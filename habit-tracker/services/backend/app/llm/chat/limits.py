# [review:need-review] PHASE-03/116, PHASE-03/114
# summary: the ceilings of a chat turn — the worker-wide slot counter that keeps two CLI processes from becoming three, and the watchdog that ends a turn silent on its first delta long before the overall deadline
"""
Потолки одного хода разговора.

**Слотов два, потому что процесс дорогой.** Каждый ход бэкенда `cli` — это
отдельный Node, и память на него считается сотнями мегабайт. Система
однопользовательская: три диалога, в которые пишут разом, не имеют права
поднять три процесса. Счётчик здесь, а не в ручке, потому что он общий на
процесс воркера и обязан освобождаться на любом выходе.

**Молчание лечится раньше общего таймаута.** CLI, не отдавший ни одного куска
текста за первые секунды, обычно уже не заговорит: он либо не смог
аутентифицироваться, либо ждёт того, чего не дождётся. Ждать его все сто
восемьдесят секунд — значит держать слот и соединение ради заведомо мёртвого
хода. Поэтому у потока два срока: до первого `delta` — короткий, на весь ход —
общий.

**Убийство процесса живёт не здесь.** `terminate_process` стоит в
`app/llm/cli.py`: жизненный цикл процесса — забота модуля, который его и
запускает, а вотчдогу достаточно закрыть источник, чтобы сработал его `finally`.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from types import TracebackType

from app.core.config import settings
from app.llm.chat.client import CHUNK_DELTA, ChatChunk
from app.llm.client import LLMError

# Машинные коды отказа. В `chat_messages.error_code` уходит одно из них — не
# текст исключения, у которого нет обязательства не содержать куска разговора.
ERROR_TURN_TIMEOUT = "turn_timeout"
ERROR_FIRST_DELTA_TIMEOUT = "first_delta_timeout"
ERROR_SLOTS_BUSY = "chat_slots_busy"


class SlotsBusyError(Exception):
    """Свободного слота не нашлось за отведённое время."""


class TurnSlots:
    """
    Потолок одновременных ходов на процесс воркера.

    Семафор создаётся лениво и заново на каждый цикл событий. Это не
    осторожность ради осторожности: `asyncio.Semaphore` привязывается к циклу
    при первом ожидании, а тесты гоняют каждый случай в своём цикле, и один
    экземпляр на модуль падал бы со второго теста подряд. В рабочем процессе
    цикл один, и ветка пересоздания срабатывает ровно раз.
    """

    def __init__(self, capacity: int) -> None:
        self._capacity = capacity
        self._loop: asyncio.AbstractEventLoop | None = None
        self._semaphore: asyncio.Semaphore | None = None
        self._in_flight = 0

    @property
    def capacity(self) -> int:
        """Сколько ходов разрешено одновременно."""
        return self._capacity

    @property
    def in_flight(self) -> int:
        """Сколько ходов держат слот прямо сейчас."""
        return self._in_flight

    def _current(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        if self._loop is not loop or self._semaphore is None:
            self._loop = loop
            self._semaphore = asyncio.Semaphore(self._capacity)
            self._in_flight = 0
        return self._semaphore

    async def acquire(self, *, wait_seconds: float) -> None:
        """
        Занять слот, подождав не дольше `wait_seconds`.

        Ожидание ограничено намеренно: очередь без предела — это воркер,
        занятый ходом, которого человек уже не ждёт. Не дождавшись, поднимаем
        `SlotsBusyError`, и человек получает внятный отказ вместо третьего Node.
        """
        semaphore = self._current()
        if wait_seconds <= 0:
            if semaphore.locked():
                raise SlotsBusyError(ERROR_SLOTS_BUSY)
            await semaphore.acquire()
        else:
            try:
                await asyncio.wait_for(semaphore.acquire(), timeout=wait_seconds)
            except asyncio.TimeoutError as exc:
                raise SlotsBusyError(ERROR_SLOTS_BUSY) from exc
        self._in_flight += 1

    def release(self) -> None:
        """Освободить слот; на уже освобождённом — ничего не делать."""
        if self._semaphore is None or self._in_flight == 0:
            return
        self._in_flight -= 1
        self._semaphore.release()


class TurnSlot:
    """
    Занятый слот как объект, который не страшно освободить дважды.

    Слот занимается в ручке — иначе отказ не станет кодом HTTP, — а
    освобождается в `finally` генератора, иначе упавший ход запирает потолок
    навсегда. Между этими двумя местами лежит путь, на котором ход может и не
    начаться, поэтому освобождение обязано быть идемпотентным.
    """

    def __init__(self, slots: TurnSlots) -> None:
        self._slots = slots
        self._held = True

    @property
    def held(self) -> bool:
        """Держится ли слот прямо сейчас."""
        return self._held

    def release(self) -> None:
        """Вернуть слот, если он ещё держится."""
        if not self._held:
            return
        self._held = False
        self._slots.release()

    def __enter__(self) -> "TurnSlot":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()


# Потолок на процесс воркера.
_turn_slots = TurnSlots(settings.CHAT_MAX_CONCURRENT_TURNS)


def turn_slots() -> TurnSlots:
    """Общий счётчик слотов этого процесса."""
    return _turn_slots


def reset_turn_slots(capacity: int | None = None) -> TurnSlots:
    """Пересобрать счётчик — точка, за которую тест берёт потолок в одну строку."""
    global _turn_slots
    _turn_slots = TurnSlots(
        settings.CHAT_MAX_CONCURRENT_TURNS if capacity is None else capacity
    )
    return _turn_slots


async def acquire_turn_slot() -> TurnSlot:
    """Занять слот по настройкам приложения; `SlotsBusyError` — свободных нет."""
    slots = turn_slots()
    await slots.acquire(wait_seconds=float(settings.CHAT_SLOT_WAIT_SECONDS))
    return TurnSlot(slots)


async def guard_stream(
    source: AsyncIterator[ChatChunk],
    *,
    first_delta_timeout: float,
    total_timeout: float,
) -> AsyncIterator[ChatChunk]:
    """
    Поток кусков под двумя сроками: до первого `delta` и на весь ход.

    Пока текста не было, действует короткий срок; первый же `delta` переводит
    ход на общий. Оба истечения — `LLMError` с машинным кодом, и коды разные:
    «замолчал на старте» и «не уложился» лечатся по-разному, и различать их
    надо в `error_code`, а не в чужой голове.

    Источник закрывается в `finally` при любом выходе, включая отмену. Именно
    это закрытие и убивает процесс CLI: его собственный `finally` — то место,
    где процесс получает `kill`.
    """
    iterator = source.__aiter__()
    started = time.monotonic()
    seen_delta = False
    try:
        while True:
            elapsed = time.monotonic() - started
            budget = total_timeout - elapsed
            code = ERROR_TURN_TIMEOUT
            if not seen_delta:
                silence = first_delta_timeout - elapsed
                if silence < budget:
                    budget = silence
                    code = ERROR_FIRST_DELTA_TIMEOUT
            if budget <= 0:
                raise LLMError(code)
            try:
                chunk = await asyncio.wait_for(iterator.__anext__(), timeout=budget)
            except StopAsyncIteration:
                return
            except asyncio.TimeoutError as exc:
                raise LLMError(code) from exc
            if chunk.kind == CHUNK_DELTA:
                seen_delta = True
            yield chunk
    finally:
        aclose = getattr(iterator, "aclose", None)
        if aclose is not None:
            await aclose()


def guarded_turn(
    source: AsyncIterator[ChatChunk], *, budget: float | None = None
) -> AsyncIterator[ChatChunk]:
    """
    Тот же поток под сроками из настроек — одна точка, где они читаются.

    `budget` — сколько секунд осталось **всему ходу**, а не этому потоку. Ход с
    именованными выборками (`#114`) состоит из нескольких потоков подряд, и без
    общего остатка каждый из них получал бы полный срок: три захода по сто
    восемьдесят секунд — это девять минут ожидания под одним вопросом. Срок
    хода назван один раз в настройках и не умножается на число заходов.
    """
    total = float(settings.CHAT_TURN_TIMEOUT_SECONDS)
    if budget is not None:
        total = min(total, budget)
    return guard_stream(
        source,
        first_delta_timeout=float(settings.CHAT_FIRST_DELTA_TIMEOUT_SECONDS),
        total_timeout=total,
    )
