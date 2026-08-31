# [review:need-review] PHASE-03/151
# summary: ночной прогон-страховка — под `pg_advisory_xact_lock`, на завтрашнюю дату от `local_date()`, только скелет и только когда плана нет и завтра рабочий день; модель не зовётся ни при каких условиях, план помечается `needs_review`
"""
Ночной прогон-страховка: день не остаётся без плана.

**Нужен ровно дню, который не закрыли.** Закрытый вечером день план на завтра
уже собрал — контекст был в голове, это лучший момент. А дни без итога есть
(15-16.08, 21-27.08), и каждое такое утро начиналось с пустоты.

**Строит только скелет.** LLM-план по дню, которого никто не закрывал, собрался
бы из пустоты и выглядел бы убедительнее, чем есть, — худший вид ошибки в
системе, которой доверяют утро. Модель здесь не зовётся ни при каких условиях, и
это проверяется тестом, а не обещанием.

**Пометка `needs_review` вместо тишины.** Человек утром видит «собран ночью, не
проверен», а не думает, что план кто-то продумал. Снимается первой правкой или
первой отметкой — то есть действием, а не кнопкой «я посмотрел».

**Два заслона от двойного прогона.** Первый — устройство `#108`: планировщик
один, репликами не масштабируется. Второй — `pg_advisory_xact_lock` здесь: он
защищает и от ручного запуска рядом с расписанием, где первого заслона нет.
Блокировка транзакционная: снимается коммитом или откатом, и забыть её нельзя.

**Своей арифметики по `day_start_hour` тут нет.** Завтрашняя дата — это
`today_local() + 1 день`, где `today_local` читает опубликованную границу дня
(`#107`). Три часа ночи считаются по часовому поясу правил, а не по UTC сервера,
ровно потому, что вопрос «какое сегодня число» имеет в проекте один ответ.

Прогон руками — той же командой, что и по расписанию:

    uv run python -m app.jobs.nightly
    uv run python -m app.jobs.nightly --for 2026-08-30
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Sequence
from datetime import date, timedelta
from enum import Enum

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.daytime import today_local
from app.core.locks import lock_key
from app.crud import day as day_crud
from app.crud import plan as plan_crud
from app.crud import plan_violation as violation_crud
from app.day import constraints, skeleton
from app.day.plan_validate import PlanRejected
from app.day.rules import KIND_WORK, NoRuleForDate, day_kind
from app.models.plan_revision import AUTHOR_FALLBACK

logger = logging.getLogger(__name__)

__all__ = ["JOB_NAME", "NightlyOutcome", "nightly_once", "run_nightly"]

# Имя задания: оно же ключ блокировки и строка в `deploy/README.md`.
JOB_NAME = "nightly_skeleton"

# Сколько ждать один прогон. Скелет — чистая арифметика по строке правила плюс
# одна запись; минуты здесь были бы не «долго», а «сломалось».
NIGHTLY_TIMEOUT_SECONDS = 120.0

# Раз в сутки. Точный час берётся не отсюда: планировщик `#108` гоняет задания
# интервалом, и «03:00» — это интервал в сутки от первого прогона воркера.
# Прогон идемпотентен, поэтому попадание в другой час ничего не портит: день,
# у которого план уже есть, не пишет ничего.
NIGHTLY_INTERVAL_SECONDS = 24 * 60 * 60.0


class NightlyOutcome(Enum):
    """
    Чем кончился прогон — и с каким кодом выходит команда.

    Кодов больше одного намеренно: «написал скелет», «план уже был» и «завтра
    выходной» — три разных ответа, и человек, посмотревший на код возврата,
    должен отличать их без чтения логов.
    """

    WRITTEN = ("written", 0)
    PLAN_EXISTS = ("plan_exists", 10)
    DAY_OFF = ("day_off", 11)
    NO_RULE = ("no_rule", 12)
    SKELETON_REFUSED = ("skeleton_refused", 13)

    def __init__(self, code: str, exit_code: int) -> None:
        self.code = code
        self.exit_code = exit_code


async def nightly_once(
    db: AsyncSession, *, target: date | None = None
) -> NightlyOutcome:
    """
    Один прогон в чужой сессии: взять блокировку, проверить, записать.

    Транзакцию не коммитит — это делает вызывающий. Так прогон встаёт и в
    задание планировщика, и в тест, и в ручной запуск, не заводя трёх разных
    правил о том, когда именно фиксируется запись.
    """
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key(JOB_NAME)}
    )
    on = tomorrow() if target is None else target

    try:
        rule = await day_crud.rule_for_date(db, on)
    except NoRuleForDate:
        logger.info("job %s: no canon covers the date, nothing written", JOB_NAME)
        return NightlyOutcome.NO_RULE

    if day_kind(rule, on) != KIND_WORK:
        logger.info("job %s: the next day is a day off, nothing written", JOB_NAME)
        return NightlyOutcome.DAY_OFF

    if await plan_crud.get_plan(db, on) is not None:
        logger.info(
            "job %s: the next day already has a plan, nothing written", JOB_NAME
        )
        return NightlyOutcome.PLAN_EXISTS

    day = await day_crud.ensure_day(db, on)
    built = skeleton.skeleton_plan(day.day_date, rule)
    blocking = constraints.check_all(built.draft, rule)
    if blocking:
        # Скелет, нарушивший собственные правила, — ошибка генератора, а не
        # свойство дня. Строки нарушений записываются, план не пишется.
        await violation_crud.record_violations(
            db, day.day_date, blocking, origin=constraints.ORIGIN_FALLBACK
        )
        logger.error(
            "job %s: the skeleton broke its own canon, nothing written", JOB_NAME
        )
        return NightlyOutcome.SKELETON_REFUSED

    document = violation_crud.skeleton_document(built, rule)
    try:
        stored = await plan_crud.replace_plan(
            db, day.day_date, rule, document, author=AUTHOR_FALLBACK
        )
    except PlanRejected:
        # Текст отказа не логируется: в нём стоит текст пункта.
        logger.error("job %s: the plan was refused on write, nothing written", JOB_NAME)
        return NightlyOutcome.SKELETON_REFUSED

    # Единственное, чем ночной план отличается от скелета, собранного руками:
    # его никто не смотрел, и утром это написано на экране.
    stored.needs_review = True
    await db.flush()
    await violation_crud.clear_violations(
        db, day.day_date, origin=constraints.ORIGIN_FALLBACK
    )
    logger.info("job %s: a skeleton was written for the next day", JOB_NAME)
    return NightlyOutcome.WRITTEN


def tomorrow() -> date:
    """
    Завтра — от `today_local()`, а не от `datetime.now()`.

    Своей арифметики по `day_start_hour` здесь нет и быть не должно: ответ на
    вопрос «какое сегодня число» в проекте один (`#107`), и прогон в 03:00 по
    часовому поясу правил обязан получить его же.
    """
    return today_local() + timedelta(days=1)


async def run_nightly() -> None:
    """
    Задание планировщика: своя сессия, свой коммит, исключения наружу.

    Ничего не возвращает — реестр `#108` принимает корутину без результата и
    сам считает исход прогона. Код возврата нужен только человеку, запустившему
    команду руками, и его считает `main`.
    """
    async with AsyncSessionLocal() as session:
        # Границу дня публикует таблица правил; в свежем процессе её никто ещё
        # не читал, а `tomorrow()` спрашивает именно её.
        await day_crud.list_rules(session)
        outcome = await nightly_once(session)
        if outcome is NightlyOutcome.WRITTEN:
            await session.commit()
        else:
            await session.rollback()


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.jobs.nightly",
        description=(
            "Ночной прогон-страховка: скелет плана на завтра, если плана нет и "
            "завтра рабочий день. Модель не зовётся."
        ),
    )
    parser.add_argument(
        "--for",
        dest="target",
        type=date.fromisoformat,
        default=None,
        help="Дата, на которую собрать план. По умолчанию — завтра",
    )
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> NightlyOutcome:
    async with AsyncSessionLocal() as session:
        await day_crud.list_rules(session)
        outcome = await nightly_once(session, target=args.target)
        if outcome is NightlyOutcome.WRITTEN:
            await session.commit()
        else:
            await session.rollback()
        return outcome


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа `python -m app.jobs.nightly`."""
    logging.basicConfig(level=logging.INFO)
    outcome = asyncio.run(_run(_parse_args(argv)))
    print(f"nightly: {outcome.code}")
    return outcome.exit_code


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
