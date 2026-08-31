"""
Тесты единственного планировщика фоновых задач.

Здесь проверяются не задания (их приносят `#99`, `#104`, `#151`), а свойства
процесса: что планировщик один, что он не заводится внутри веб-воркера, что
падение одного задания не уносит другое, что второй экземпляр не делает работу
параллельно и что `SIGTERM` даёт закончить начатое.

Часть тестов ходит в базу: сессионная блокировка `pg_try_advisory_lock` — не та
вещь, которую имеет смысл подделывать, весь её смысл в поведении двух настоящих
соединений.
"""

# [review:need-review] PHASE-03/108
# summary: the scheduler's process properties — no scheduler inside app.main, failure isolation between jobs, the advisory lock a second instance does not get, SIGTERM waiting out the running job, and the grep invariant against cron and stray scheduling asyncio tasks
import asyncio
import os
import re
import signal
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.scheduling.registry import (
    JobFunc,
    JobOutcome,
    JobRegistry,
    JobRunner,
    ScheduledJob,
    lock_key,
    registry,
    try_lock,
    unlock,
)
from app.worker import (
    describe_schedule,
    format_interval,
    install_signal_handlers,
    run_worker,
)
from tests.conftest import TEST_DATABASE_URL

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]
DEPLOY_README = REPO_ROOT / "deploy" / "README.md"

# Интервал тестовых заданий: планировщик должен успеть отработать несколько
# прогонов за время теста, поэтому он меряется в десятках миллисекунд.
FAST_INTERVAL = 0.05
FAST_TIMEOUT = 5.0


@pytest.fixture()
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """
    Фабрика сессий к тестовой базе с `NullPool`.

    Пул здесь навредил бы: два «экземпляра воркера» в тесте обязаны сидеть на
    разных соединениях, иначе сессионная блокировка достанется обоим.
    """
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool, echo=False)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


def job(
    name: str,
    func: JobFunc,
    interval: float = FAST_INTERVAL,
    timeout: float = FAST_TIMEOUT,
) -> ScheduledJob:
    """Тестовое задание с быстрым интервалом."""
    return ScheduledJob(
        name=name,
        interval_seconds=interval,
        timeout_seconds=timeout,
        func=func,
        summary=f"test job {name}",
    )


class TestScheduledJob:
    """Что реестр отказывается принимать."""

    def test_name_must_be_lower_snake_case(self) -> None:
        async def noop() -> None:
            return None

        with pytest.raises(ValueError, match="lower_snake_case"):
            ScheduledJob(
                name="Poll ClickUp",
                interval_seconds=1,
                timeout_seconds=1,
                func=noop,
                summary="x",
            )

    def test_timeout_is_mandatory_and_positive(self) -> None:
        async def noop() -> None:
            return None

        with pytest.raises(ValueError, match="timeout_seconds must be positive"):
            ScheduledJob(
                name="poll",
                interval_seconds=1,
                timeout_seconds=0,
                func=noop,
                summary="x",
            )

    def test_interval_must_be_positive(self) -> None:
        async def noop() -> None:
            return None

        with pytest.raises(ValueError, match="interval_seconds must be positive"):
            ScheduledJob(
                name="poll",
                interval_seconds=0,
                timeout_seconds=1,
                func=noop,
                summary="x",
            )

    def test_summary_is_mandatory(self) -> None:
        async def noop() -> None:
            return None

        with pytest.raises(ValueError, match="summary"):
            ScheduledJob(
                name="poll",
                interval_seconds=1,
                timeout_seconds=1,
                func=noop,
                summary="   ",
            )

    def test_duplicate_name_is_refused(self) -> None:
        async def noop() -> None:
            return None

        jobs = JobRegistry()
        jobs.register(job("poll", noop))
        with pytest.raises(ValueError, match="already registered"):
            jobs.register(job("poll", noop))

    def test_lock_key_is_stable_per_name(self) -> None:
        assert lock_key("heartbeat") == lock_key("heartbeat")
        assert lock_key("heartbeat") != lock_key("retention")
        # bigint, иначе postgres откажется принимать ключ
        assert -(2**63) <= lock_key("heartbeat") < 2**63


class TestJobRunner:
    """Блокировка, таймаут и пойманное исключение — на живой базе."""

    async def test_successful_run_reports_done(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        calls: list[str] = []

        async def work() -> None:
            calls.append("ran")

        runner = JobRunner(session_factory)
        assert await runner.run(job("ok_job", work)) is JobOutcome.DONE
        assert calls == ["ran"]
        assert runner.in_flight == frozenset()

    async def test_exception_is_caught_and_the_run_reports_failed(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        async def boom() -> None:
            raise ValueError("secret@example.com must not reach the log")

        runner = JobRunner(session_factory)
        assert await runner.run(job("boom_job", boom)) is JobOutcome.FAILED

    async def test_failure_is_logged_by_class_without_the_message(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        async def boom() -> None:
            raise ValueError("daniil@example.com")

        runner = JobRunner(session_factory)
        with caplog.at_level("ERROR"):
            await runner.run(job("pii_job", boom))
        logged = "\n".join(record.getMessage() for record in caplog.records)
        assert "ValueError" in logged
        assert "example.com" not in logged

    async def test_job_over_its_timeout_is_cancelled(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        finished = False

        async def slow() -> None:
            nonlocal finished
            await asyncio.sleep(5)
            finished = True

        runner = JobRunner(session_factory)
        outcome = await runner.run(job("slow_job", slow, timeout=0.05))
        assert outcome is JobOutcome.TIMED_OUT
        assert finished is False

    async def test_second_instance_does_not_get_the_lock_and_skips_the_run(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Второй воркер пропускает прогон, а не ставит его в очередь — и говорит об этом."""
        calls: list[str] = []

        async def work() -> None:
            calls.append("ran")

        held = job("locked_job", work)
        async with session_factory() as first_instance:
            assert await try_lock(first_instance, held.name) is True
            try:
                runner = JobRunner(session_factory)
                with caplog.at_level("INFO"):
                    assert await runner.run(held) is JobOutcome.SKIPPED_LOCKED
                assert calls == []
            finally:
                await unlock(first_instance, held.name)
        logged = "\n".join(record.getMessage() for record in caplog.records)
        assert "job locked_job skipped" in logged
        assert "held by another instance" in logged

    async def test_the_lock_is_released_after_the_run(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """Иначе одного прогона хватило бы, чтобы задание больше не запускалось."""

        async def work() -> None:
            return None

        released = job("released_job", work)
        runner = JobRunner(session_factory)
        assert await runner.run(released) is JobOutcome.DONE
        async with session_factory() as probe:
            assert await try_lock(probe, released.name) is True
            await unlock(probe, released.name)

    async def test_the_lock_is_released_even_when_the_job_raises(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        async def boom() -> None:
            raise RuntimeError("no")

        failing = job("failing_lock_job", boom)
        runner = JobRunner(session_factory)
        assert await runner.run(failing) is JobOutcome.FAILED
        async with session_factory() as probe:
            assert await try_lock(probe, failing.name) is True
            await unlock(probe, failing.name)


class TestWorkerLoop:
    """Свойства процесса: изоляция сбоя и корректное завершение."""

    async def test_a_failing_job_keeps_its_schedule_and_spares_the_other(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """Оба задания видны на следующем интервале, хотя одно падает всегда."""
        failures = 0
        successes = 0

        async def always_fails() -> None:
            nonlocal failures
            failures += 1
            raise RuntimeError("this one is broken")

        async def always_works() -> None:
            nonlocal successes
            successes += 1

        jobs = JobRegistry()
        jobs.register(job("broken", always_fails))
        jobs.register(job("healthy", always_works))

        stop = asyncio.Event()
        worker = asyncio.create_task(
            run_worker(
                jobs=jobs,
                runner=JobRunner(session_factory),
                stop=stop,
                handle_signals=False,
            )
        )
        await asyncio.sleep(FAST_INTERVAL * 12)
        stop.set()
        await asyncio.wait_for(worker, timeout=5)

        assert failures >= 2, "the broken job dropped off the schedule"
        assert successes >= 2, "the broken job took the healthy one down with it"

    async def test_stop_waits_for_the_running_job_instead_of_cutting_it(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """`SIGTERM` во время задания даёт завершение после его конца."""
        started = asyncio.Event()
        finished = False

        async def slow() -> None:
            nonlocal finished
            started.set()
            await asyncio.sleep(0.3)
            finished = True

        jobs = JobRegistry()
        jobs.register(job("slow_but_finishes", slow))

        stop = asyncio.Event()
        worker = asyncio.create_task(
            run_worker(
                jobs=jobs,
                runner=JobRunner(session_factory),
                stop=stop,
                handle_signals=False,
            )
        )
        await asyncio.wait_for(started.wait(), timeout=5)
        stop.set()
        await asyncio.wait_for(worker, timeout=5)

        assert finished is True

    async def test_sigterm_asks_the_worker_to_stop(self) -> None:
        """Настоящий сигнал, а не только внутреннее событие."""
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        install_signal_handlers(loop, stop)
        try:
            os.kill(os.getpid(), signal.SIGTERM)
            await asyncio.wait_for(stop.wait(), timeout=5)
        finally:
            loop.remove_signal_handler(signal.SIGTERM)
            loop.remove_signal_handler(signal.SIGINT)
        assert stop.is_set()

    def test_the_schedule_is_printed_with_intervals(self) -> None:
        lines = describe_schedule(registry)
        assert lines, "an empty schedule would say nothing at startup"
        for scheduled in registry:
            line = next(
                one for one in lines if one.startswith(f"job {scheduled.name}:")
            )
            assert format_interval(scheduled.interval_seconds) in line
            assert format_interval(scheduled.timeout_seconds) in line

    def test_an_empty_registry_says_so_rather_than_printing_nothing(self) -> None:
        assert describe_schedule(JobRegistry()) == ["no background jobs registered"]

    def test_a_long_external_command_is_marked_in_the_schedule(self) -> None:
        """
        Задел под запуск `claude` CLI из воркера (`#148`/`#149`): минуты у такого
        задания — норма, и лог обязан отличать её от зависания.
        """

        async def noop() -> None:
            return None

        jobs = JobRegistry()
        jobs.register(
            ScheduledJob(
                name="nightly_plan",
                interval_seconds=86400,
                timeout_seconds=900,
                func=noop,
                summary="the claude CLI run this worker will own",
                long_running=True,
            )
        )
        assert "long external command" in describe_schedule(jobs)[0]


class TestNoSecondScheduler:
    """Запреты тикета проверяются тестом, а не чтением кода."""

    def test_importing_app_main_starts_no_scheduler(self) -> None:
        """
        gunicorn импортирует `app.main`. Если оттуда виден APScheduler или
        `app.worker`, значит планировщик поехал внутрь веб-воркера — двойной
        прогон в двух процессах и гонка за курсор.

        Отдельный процесс, потому что pytest к этому моменту уже импортировал
        и то и другое своими тестами.
        """
        probe = (
            "import sys, app.main;"
            "banned = [m for m in ('apscheduler', 'app.worker', 'app.scheduling')"
            " if m in sys.modules];"
            "print(','.join(banned))"
        )
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            cwd=BACKEND_ROOT,
            timeout=120,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "", (
            "importing app.main pulled in the scheduler: " + result.stdout.strip()
        )

    def test_no_cron_and_no_stray_scheduling_task(self) -> None:
        """
        grep-инвариант: ни `crontab`/`cron.d` в коде, ни планирующей
        `asyncio`-задачи вне `app/worker.py`.

        Прозу (`.md`) первое правило не трогает — там cron упоминается как
        инструкция по бэкапу (`#96`). Зато следующий тест разбирает саму
        crontab-врезку `deploy/README.md` и не пускает туда прикладную логику.
        Из первого правила исключён этот файл: запрещённые слова написаны в
        нём самом. Из второго исключены тесты: конкурентность планировщика
        проверяется параллельными задачами, и запрещать их тесту — значит
        запрещать проверку.
        """
        tracked = _tracked_files()
        this_file = Path(__file__).resolve()
        cron = re.compile(r"crontab|cron\.d")
        scheduling_task = re.compile(
            r"asyncio\.create_task|ensure_future|loop\.call_later|\.call_at\("
        )
        apscheduler_import = re.compile(
            r"^\s*(from|import)\s+apscheduler", re.MULTILINE
        )

        cron_hits: list[str] = []
        task_hits: list[str] = []
        scheduler_hits: list[str] = []
        for path in tracked:
            absolute = (REPO_ROOT / path).resolve()
            text = _read(absolute)
            if text is None:
                continue
            if path.suffix != ".md" and absolute != this_file and cron.search(text):
                cron_hits.append(str(path))
            if path.suffix != ".py" or path.parts[-2] == "tests":
                continue
            if path.name != "worker.py" and scheduling_task.search(text):
                task_hits.append(str(path))
            if path.name != "worker.py" and apscheduler_import.search(text):
                scheduler_hits.append(str(path))

        assert cron_hits == [], f"cron carrying logic: {cron_hits}"
        assert task_hits == [], f"asyncio scheduling outside worker.py: {task_hits}"
        assert scheduler_hits == [], f"apscheduler outside worker.py: {scheduler_hits}"

    def test_the_host_crontab_in_the_readme_only_runs_the_backup_scripts(self) -> None:
        """
        Хостовый cron остаётся ровно за скриптами бэкапа `#96`. Строка,
        зовущая оттуда python или docker, — это возвращение второго
        планировщика через документацию.
        """
        lines = [
            line
            for line in DEPLOY_README.read_text(encoding="utf-8").splitlines()
            if re.match(r"^[\d*]+\s+[\d*]+\s+", line.strip())
        ]
        assert lines, "the backup schedule disappeared from deploy/README.md"
        for line in lines:
            assert re.search(r"/deploy/[a-z-]+\.sh", line), line
            assert "python" not in line and "docker" not in line, line


class TestReadmeMatchesTheRegistry:
    """Список фоновых заданий в `deploy/README.md` сходится с реестром."""

    def test_every_registered_job_has_its_row(self) -> None:
        readme = DEPLOY_README.read_text(encoding="utf-8")
        rows = {
            name: (schedule, timeout, summary)
            for name, schedule, timeout, summary in re.findall(
                r"^\|\s*`([a-z_]+)`\s*\|([^|]*)\|([^|]*)\|([^|]*)\|\s*$",
                readme,
                re.MULTILINE,
            )
        }
        assert set(rows) == set(registry.names), (
            "deploy/README.md and app/scheduling/registry.py disagree about the "
            "list of background jobs"
        )
        for scheduled in registry:
            schedule, timeout, summary = rows[scheduled.name]
            assert schedule.strip() == format_interval(scheduled.interval_seconds)
            assert timeout.strip() == format_interval(scheduled.timeout_seconds)
            assert summary.strip() == scheduled.summary


class TestWorkerService:
    """Контейнер воркера в compose-файлах."""

    def test_dev_compose_runs_the_worker_on_the_backend_image(self) -> None:
        compose = (REPO_ROOT / "habit-tracker" / "docker-compose.yml").read_text(
            encoding="utf-8"
        )
        worker = _compose_service(compose, "worker")
        assert "python -m app.worker" in worker
        assert "build: ./services/backend" in worker
        assert "ports:" not in worker, "the worker publishes no port"

    def test_prod_compose_keeps_one_worker_that_restarts(self) -> None:
        compose = (REPO_ROOT / "deploy" / "docker-compose.prod.yml").read_text(
            encoding="utf-8"
        )
        worker = _compose_service(compose, "worker")
        assert "restart: always" in worker
        assert "replicas: 1" in worker
        assert "python -m app.worker" in worker


def _compose_service(compose: str, name: str) -> str:
    """Кусок compose-файла, относящийся к одному сервису."""
    match = re.search(
        rf"^  {name}:\n(?P<body>(?:(?:    .*)?\n)*)", compose, re.MULTILINE
    )
    assert match is not None, f"compose file has no service {name!r}"
    return match.group("body")


def _tracked_files() -> list[Path]:
    """Файлы под версией — список, по которому идёт grep-инвариант."""
    listing = subprocess.run(
        ["git", "ls-files"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=120,
    )
    assert listing.returncode == 0, listing.stderr
    return [Path(line) for line in listing.stdout.splitlines() if line]


def _read(path: Path) -> str | None:
    """Текст файла; двоичные и исчезнувшие пропускаются."""
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
        return None
