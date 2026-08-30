# [review:need-review] PHASE-03/108
# summary: the one registry of background jobs (name, interval, timeout, function) and what a single run is — pg_try_advisory_lock by name, a timeout, and a failure logged by exception class that leaves the schedule alive
"""
Реестр фоновых заданий и правила одного прогона.

Фаза приносила в один сервис три механизма фоновой работы: APScheduler в
отдельном контейнере, `asyncio`-задачу внутри веб-воркера и системный cron на
VPS. Три планировщика — три источника гонок за одну строку и три места, где
что-то тихо не запустилось. Планировщик остаётся один (`app/worker.py`), а
список того, что он гоняет, лежит здесь и только здесь: иначе ответ на вопрос
«что вообще крутится в фоне» собирается grep'ом по репозиторию.

Три свойства прогона вписаны в код, а не в дисциплину задания.

**Блокировка.** Перед вызовом функции прогон берёт `pg_try_advisory_lock` по
имени задания. Не взял — прогон пропущен, а не поставлен в очередь: два
запущенных контейнера не должны делать одну работу дважды, и не должны копить
её на потом. Блокировка сессионная, снимается явно в `finally`, потому что
соединение возвращается в пул живым и `ROLLBACK` сессионных блокировок не
снимает.

**Таймаут.** У каждого задания свой, и он обязателен. Задел назван в тикете
прямо: этот воркер потом будет запускать `claude` CLI на сервере, а внешняя
команда без таймаута — это заклиненное расписание, где остальные задания молчат
и никто не знает почему. Признак `long_running` не меняет поведение
планировщика, он говорит человеку в логе и в `deploy/README.md`, что минуты
здесь — норма, а не авария.

**Изоляция сбоя.** Исключение задания ловится, пишется классом (`ValueError`),
без текста и без traceback: сообщение исключения — первое место, куда утекают
имя, адрес и содержимое записи. Задание остаётся на расписании: упавший опрос
источника не должен уносить с собой ночную ретенцию.

Идемпотентность здесь не обеспечивается. Планировщик гарантирует «запустилось
не чаще, чем раз в интервал»; «повторный прогон не портит данные» — дело кода
задания.
"""

import asyncio
import hashlib
import logging
import re
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from enum import Enum

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

# Задание — корутина без аргументов: всё, что ей нужно, она берёт сама.
# Аргументы в реестре означали бы состояние, живущее между прогонами.
JobFunc = Callable[[], Awaitable[None]]

# Имя задания одновременно ключ блокировки, id в планировщике и строка в
# `deploy/README.md`, поэтому оно ограничено алфавитом, который переживает все три.
JOB_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

# Разрядность ключа `pg_advisory_lock`: он принимает один bigint.
LOCK_KEY_BYTES = 8

# Пульс: единственное задание, которое приносит сам этот тикет. Оно отвечает на
# вопрос «планировщик вообще жив и база из воркера видна» строкой в логе —
# без него первое подтверждение работы воркера появилось бы только с `#99`.
HEARTBEAT_INTERVAL_SECONDS = 300.0
HEARTBEAT_TIMEOUT_SECONDS = 30.0


class JobOutcome(Enum):
    """Чем кончился один прогон задания."""

    DONE = "done"
    SKIPPED_LOCKED = "skipped_locked"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


def lock_key(name: str) -> int:
    """
    Ключ `pg_advisory_lock` для задания с этим именем.

    Хеш, а не порядковый номер: номер зависит от порядка регистрации, и
    добавление задания в середину списка молча переназначило бы блокировки всем
    следующим. `blake2b` берётся ради фиксированной длины, не ради стойкости.
    """
    digest = hashlib.blake2b(name.encode("utf-8"), digest_size=LOCK_KEY_BYTES).digest()
    return int.from_bytes(digest, "big", signed=True)


@dataclass(frozen=True)
class ScheduledJob:
    """
    Одно фоновое задание: имя, интервал, таймаут, функция.

    `summary` — та же строка, что стоит в таблице заданий `deploy/README.md`;
    она живёт рядом с интервалом, чтобы описание и расписание правились одной
    рукой.
    """

    name: str
    interval_seconds: float
    timeout_seconds: float
    func: JobFunc
    summary: str
    long_running: bool = False

    def __post_init__(self) -> None:
        if not JOB_NAME_PATTERN.match(self.name):
            raise ValueError(
                f"job name {self.name!r} must be lower_snake_case: it is also the "
                "advisory-lock key and the row in deploy/README.md"
            )
        if self.interval_seconds <= 0:
            raise ValueError(f"job {self.name}: interval_seconds must be positive")
        if self.timeout_seconds <= 0:
            raise ValueError(
                f"job {self.name}: timeout_seconds must be positive — a background "
                "job without a deadline jams the whole schedule"
            )
        if not self.summary.strip():
            raise ValueError(
                f"job {self.name}: summary is what deploy/README.md prints; "
                "an empty one makes the list of background jobs unreadable"
            )


class JobRegistry:
    """
    Список фоновых заданий системы.

    Отдельный класс, а не глобальный список, ровно затем, чтобы тест собирал
    свой набор заданий и не трогал боевой.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, ScheduledJob] = {}

    def register(self, job: ScheduledJob) -> ScheduledJob:
        """Добавить задание. Повторное имя — ошибка, а не молчаливая замена."""
        if job.name in self._jobs:
            raise ValueError(
                f"job {job.name!r} is already registered: two jobs under one name "
                "would share an advisory lock and hide one of the two"
            )
        self._jobs[job.name] = job
        return job

    def __iter__(self) -> Iterator[ScheduledJob]:
        return iter(self._jobs.values())

    def __len__(self) -> int:
        return len(self._jobs)

    @property
    def names(self) -> tuple[str, ...]:
        """Имена заданий в порядке регистрации."""
        return tuple(self._jobs)

    def get(self, name: str) -> ScheduledJob:
        """Задание по имени; отсутствующее — ошибка."""
        return self._jobs[name]


async def try_lock(session: AsyncSession, name: str) -> bool:
    """Взять сессионную блокировку задания; `False` — её держит кто-то другой."""
    result = await session.execute(
        text("SELECT pg_try_advisory_lock(:key)"), {"key": lock_key(name)}
    )
    return bool(result.scalar_one())


async def unlock(session: AsyncSession, name: str) -> None:
    """Снять сессионную блокировку задания."""
    await session.execute(
        text("SELECT pg_advisory_unlock(:key)"), {"key": lock_key(name)}
    )


class JobRunner:
    """
    Исполнитель заданий реестра: блокировка, таймаут, пойманное исключение.

    Он же считает прогоны в полёте, потому что корректное завершение по
    `SIGTERM` — это «дождаться текущего задания», а APScheduler на своей стороне
    такого ожидания не даёт: `AsyncIOExecutor.shutdown` отменяет незавершённые
    задачи независимо от `wait`. Ждать приходится тому, кто знает, что запущено.
    """

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal
    ) -> None:
        self._session_factory = session_factory
        self._in_flight: set[str] = set()
        self._idle = asyncio.Event()
        self._idle.set()

    @property
    def in_flight(self) -> frozenset[str]:
        """Имена заданий, выполняющихся прямо сейчас."""
        return frozenset(self._in_flight)

    async def wait_idle(self) -> None:
        """Дождаться конца всех запущенных заданий."""
        await self._idle.wait()

    async def run(self, job: ScheduledJob) -> JobOutcome:
        """
        Выполнить задание один раз. Не поднимает исключений — их поднимает код
        задания, а расписание должно пережить любое из них.
        """
        self._in_flight.add(job.name)
        self._idle.clear()
        try:
            return await self._run_locked(job)
        except Exception as error:
            # Сюда попадает отказ самой инфраструктуры прогона: база недоступна,
            # блокировку взять не у кого. Класс — без текста: строка подключения
            # и содержимое запроса в лог не идут.
            logger.error("job %s could not start: %s", job.name, type(error).__name__)
            return JobOutcome.FAILED
        finally:
            self._in_flight.discard(job.name)
            if not self._in_flight:
                self._idle.set()

    async def _run_locked(self, job: ScheduledJob) -> JobOutcome:
        """Прогон под блокировкой: её берут до вызова и снимают всегда."""
        async with self._session_factory() as session:
            if not await try_lock(session, job.name):
                logger.info(
                    "job %s skipped: its advisory lock is held by another instance",
                    job.name,
                )
                return JobOutcome.SKIPPED_LOCKED
            try:
                return await self._call(job)
            finally:
                await unlock(session, job.name)
                await session.rollback()

    async def _call(self, job: ScheduledJob) -> JobOutcome:
        """Вызов функции задания под таймаутом, с пойманным исключением."""
        started = asyncio.get_running_loop().time()
        try:
            await asyncio.wait_for(job.func(), timeout=job.timeout_seconds)
        except asyncio.TimeoutError:
            logger.error(
                "job %s timed out after %.0fs and was cancelled",
                job.name,
                job.timeout_seconds,
            )
            return JobOutcome.TIMED_OUT
        except Exception as error:
            # Класс исключения, не сообщение: текст ошибки — первое место, куда
            # утекает содержимое записи, имя чата или адрес почты.
            logger.error("job %s failed: %s", job.name, type(error).__name__)
            return JobOutcome.FAILED
        logger.info(
            "job %s done in %.1fs",
            job.name,
            asyncio.get_running_loop().time() - started,
        )
        return JobOutcome.DONE


async def heartbeat() -> None:
    """
    Доказательство, что воркер жив и база из него видна.

    Единственное задание, которое приносит сам тикет `#108`: опрос источников,
    ретенция и ночной скелет плана приходят с `#99`, `#104` и `#151`. Без него
    ответ на вопрос «задание вообще идёт» пришлось бы ждать до первого из них.
    """
    async with AsyncSessionLocal() as session:
        await session.execute(text("SELECT 1"))
        await session.rollback()
    logger.info("job heartbeat: worker alive, database reachable")


registry = JobRegistry()

# Регистрация в одном месте — это и есть смысл файла. Задание, добавленное где-то
# ещё, не попадёт ни в лог расписания, ни в таблицу `deploy/README.md`,
# расхождение с которой ловит тест.
registry.register(
    ScheduledJob(
        name="heartbeat",
        interval_seconds=HEARTBEAT_INTERVAL_SECONDS,
        timeout_seconds=HEARTBEAT_TIMEOUT_SECONDS,
        func=heartbeat,
        summary="строка в лог: планировщик жив, база из воркера видна",
    )
)
