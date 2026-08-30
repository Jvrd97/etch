# [review:need-review] PHASE-03/108
# summary: the one background scheduler — `python -m app.worker` runs an AsyncIOScheduler over app/scheduling/registry in a single process, prints the schedule at start, coalesces missed runs and finishes the running job before exiting on SIGTERM
"""
Единственный планировщик фоновых заданий.

Запуск — `python -m app.worker`, отдельный контейнер на образе бэкенда, один
экземпляр. Два запрета вписаны в устройство, а не подразумеваются.

**Системного cron на VPS нет.** Логика, уехавшая в расписание хоста, уезжает и
из-под `mypy`, `pytest` и логов контейнера; починка выглядит как ssh и чтение
`/var/log`. Расписание хоста в проекте остаётся ровно за скриптами бэкапа
(`deploy/backup.sh` и соседи, тикет `#96`) — там нет ни строки прикладной логики.

**`asyncio`-задач с расписанием внутри веб-воркера нет.** gunicorn держит два
воркера, задача в каждом даёт двойной прогон и гонку за курсор; при этом упавший
планировщик неотличим от живого, потому что процесс продолжает отвечать на HTTP.
Проверяется тестом: импорт `app.main` не тянет ни `apscheduler`, ни этот модуль.

**Пропуск не превращается в пачку.** `coalesce=True` и `misfire_grace_time`:
воркер, простоявший час, делает один прогон каждого задания, а не двенадцать
подряд; `max_instances=1` не пускает второй прогон поверх незакончившегося.

**`SIGTERM` дожидается текущего задания.** Ждать приходится здесь:
`AsyncIOExecutor.shutdown` у APScheduler отменяет незавершённые задачи независимо
от `wait`, поэтому по сигналу планировщик сначала ставится на паузу (новые
прогоны не стартуют), потом `JobRunner` досчитывает запущенные, и только затем
планировщик гасится.

Реестр заданий — `app/scheduling/registry.py`; здесь только процесс.
"""

import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.scheduling.registry import (
    JobRegistry,
    JobRunner,
    ScheduledJob,
    registry,
)

logger = logging.getLogger("app.worker")

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"

# Насколько опоздавший прогон ещё считается прогоном, а не пропуском. Час
# покрывает перезапуск контейнера и деплой; всё, что дольше, честнее пропустить
# и дождаться следующего интервала, чем догонять.
MISFIRE_GRACE_SECONDS = 3600

# Сигналы, по которым воркер уходит корректно: docker шлёт SIGTERM, человек в
# терминале — SIGINT.
STOP_SIGNALS = (signal.SIGTERM, signal.SIGINT)

SECONDS_IN_MINUTE = 60


def configure_logging(level: int = logging.INFO) -> None:
    """
    Логи воркера — единственное окно в его работу, поэтому настраиваются явно.

    Вызывается только из `main()`: тест, запускающий воркер в своём цикле, не
    должен переписывать конфигурацию логов всему прогону pytest.
    """
    logging.basicConfig(level=level, format=LOG_FORMAT)
    # APScheduler по умолчанию молчит на WARNING и не сообщает даже о пропущенном
    # прогоне. Ему нужен свой уровень: он говорит о том, чего не видит наш код.
    logging.getLogger("apscheduler").setLevel(logging.INFO)


def format_interval(seconds: float) -> str:
    """Интервал строкой, в которой видно минуты: «900s (15 min)»."""
    if seconds >= SECONDS_IN_MINUTE:
        return f"{seconds:.0f}s ({seconds / SECONDS_IN_MINUTE:.0f} min)"
    return f"{seconds:g}s"


def describe_schedule(jobs: JobRegistry) -> list[str]:
    """
    Расписание строками для лога старта.

    Отдельная чистая функция, потому что это первое, на что смотрит человек,
    когда фоновая работа «не идёт»: контейнер, напечатавший пустое расписание,
    отвечает на вопрос сразу.
    """
    if not len(jobs):
        return ["no background jobs registered"]
    return [
        f"job {job.name}: every {format_interval(job.interval_seconds)}, "
        f"timeout {format_interval(job.timeout_seconds)}"
        + (", long external command" if job.long_running else "")
        + f" — {job.summary}"
        for job in jobs
    ]


def build_scheduler(jobs: JobRegistry, runner: JobRunner) -> AsyncIOScheduler:
    """Собрать планировщик по реестру. Расписание нигде больше не задаётся."""
    scheduler = AsyncIOScheduler()
    for job in jobs:
        scheduler.add_job(
            _job_callable(job, runner),
            trigger=IntervalTrigger(seconds=job.interval_seconds),
            id=job.name,
            name=job.name,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=MISFIRE_GRACE_SECONDS,
        )
    return scheduler


def _job_callable(
    job: ScheduledJob, runner: JobRunner
) -> Callable[[], Awaitable[None]]:
    """
    Замыкание, которое планировщик вызывает вместо функции задания.

    Смысл один: планировщик не должен звать `job.func` напрямую, иначе мимо него
    проходят и блокировка, и таймаут, и ловля исключения.
    """

    async def call() -> None:
        await runner.run(job)

    return call


def install_signal_handlers(
    loop: asyncio.AbstractEventLoop, stop: asyncio.Event
) -> None:
    """
    Повесить остановку на SIGTERM и SIGINT.

    `loop.add_signal_handler`, а не `signal.signal`: обработчик исполняется в
    цикле событий между шагами, поэтому он не может прервать задание в
    произвольной точке — он только просит воркер закончить.
    """
    for number in STOP_SIGNALS:
        loop.add_signal_handler(number, stop.set)


async def run_worker(
    jobs: JobRegistry | None = None,
    runner: JobRunner | None = None,
    stop: asyncio.Event | None = None,
    handle_signals: bool = True,
) -> None:
    """
    Поднять планировщик и держать его до сигнала остановки.

    `stop` принимается снаружи ради теста: он проверяет корректное завершение,
    не посылая сигнал живому процессу pytest.
    """
    jobs = registry if jobs is None else jobs
    runner = JobRunner() if runner is None else runner
    stop = asyncio.Event() if stop is None else stop

    if handle_signals:
        install_signal_handlers(asyncio.get_running_loop(), stop)

    scheduler = build_scheduler(jobs, runner)
    for line in describe_schedule(jobs):
        logger.info("%s", line)
    scheduler.start()
    logger.info("scheduler started: %d job(s), single instance", len(jobs))

    try:
        await stop.wait()
    finally:
        logger.info("stop requested: no new runs, waiting for the running job")
        scheduler.pause()
        await runner.wait_idle()
        scheduler.shutdown(wait=False)
        # shutdown() у AsyncIOScheduler откладывается через call_soon_threadsafe;
        # без уступки циклу процесс успел бы выйти раньше, чем он исполнится.
        await asyncio.sleep(0)
        logger.info("scheduler stopped")


def main() -> None:
    """Точка входа `python -m app.worker`."""
    configure_logging()
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
