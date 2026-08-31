# [review:need-review] PHASE-03/144
# summary: `python -m app.imports.day_stage_backfill` — доводит уже импортированные дни до четвёртого состояния «не закрывали» (дыры календаря становятся днями со стадией `open` и пустым вердиктом), ни одного вердикта не переписывает, называет списком дни, чья проза не читается однозначно, и по `--root` сверяет жёлтые и серые квадраты с тем, что отдавал `life.py`
"""
Дни, которые не закрывали, — четвёртое состояние, доведённое до уже импортированной базы.

**Зачем отдельная команда, а не второй прогон импорта.** Импорт читает файлы;
эта команда не читает ничего, кроме `--root` при сверке, и трогает ровно одну
вещь — календарь. База, в которую историю перенесли до `#143`, содержит дни без
`day`-строки там, где плана не было, и такой день на таймлайне неотличим от
проигранного: квадрата нет вовсе. После прогона он есть и он пустой.

**Ни один вердикт здесь не пишется и не стирается.** Ни разу, ни под `--apply`.
Вердикт, перенесённый прозой, пересчитать нечем: данные, по которым он
выносился, в файлах не сохранились — сохранился только ответ. Поэтому команда
умеет заводить дни и не умеет их судить, и это не осторожность, а граница:
писателя вердикта в этом модуле нет.

**Проза, прочитанная неоднозначно, попадает в отчёт, а не в базу.** Итог, под
заголовком «День выигран?» которого нет ни «да», ни «нет» («Вне игры
(выходной)»), оставляет `verdict = NULL` и называется в отчёте датой. Угадывать
такой день значило бы выдумать половину истории.

Прогон:

    uv run python -m app.imports.day_stage_backfill --dry-run
    uv run python -m app.imports.day_stage_backfill --apply
    uv run python -m app.imports.day_stage_backfill --apply --root ~/Documents/MyProj/personal-os

`--dry-run` — умолчание: команда без флагов ничего не пишет. `--root` включает
сверку по датам: файлы `summaries/**/*.md` читаются тем же `read_verdict`, что и
при импорте, и множество выигранных и проигранных дат сравнивается с тем, что
лежит в базе. Расхождение — код возврата 1 и список дат, а не строчка «похоже,
всё сошлось».
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.crud import day as day_crud
from app.day.evaluate import VERDICT_LOST, VERDICT_WON
from app.imports.personal_os import collect_summaries, read_verdict
from app.models.day import Day
from app.models.summary import SOURCE_IMPORT, DaySummary

__all__ = [
    "BackfillReport",
    "Mismatch",
    "backfill",
    "main",
    "verdicts_from_files",
]


@dataclass(frozen=True)
class Mismatch:
    """Одна дата, на которой база и файлы говорят разное."""

    day_date: date
    in_files: str | None
    in_db: str | None

    def as_line(self) -> str:
        files = self.in_files if self.in_files is not None else "нет вердикта"
        stored = self.in_db if self.in_db is not None else "нет вердикта"
        return f"расхождение {self.day_date.isoformat()}: в файлах {files}, в базе {stored}"


@dataclass
class BackfillReport:
    """
    Что прогон нашёл и что записал. Печатается CLI, читается человеком.

    `days_created` под `--dry-run` перечисляет то же, что записал бы `--apply`:
    транзакция откатывается, а не пропускается, поэтому список честный, а не
    предсказанный второй веткой кода.
    """

    applied: bool = False
    days_created: list[date] = field(default_factory=list)
    open_days: list[date] = field(default_factory=list)
    migrated_won: list[date] = field(default_factory=list)
    migrated_lost: list[date] = field(default_factory=list)
    unjudged: list[date] = field(default_factory=list)
    checked_against_files: bool = False
    mismatches: list[Mismatch] = field(default_factory=list)

    def as_lines(self) -> list[str]:
        return [
            f"режим: {'запись' if self.applied else 'сухой прогон'}",
            f"дней заведено: {_dates(self.days_created)}",
            f"дней без итога (stage=open, verdict=NULL): {len(self.open_days)}",
            f"вердиктов из записи, выигран: {len(self.migrated_won)}",
            f"вердиктов из записи, проигран: {len(self.migrated_lost)}",
            f"итогов без вердикта (проза неоднозначна): {_dates(self.unjudged)}",
            f"сверка с файлами: {'да' if self.checked_against_files else 'нет'}",
            f"расхождений: {len(self.mismatches)}",
        ]


def _dates(dates: Sequence[date]) -> str:
    """Даты списком; «нет», когда список пуст."""
    return ", ".join(one.isoformat() for one in dates) if dates else "нет"


def verdicts_from_files(root: Path) -> dict[date, str | None]:
    """
    Вердикт каждого `summaries/**/*.md` под `root`, прочитанный как при импорте.

    Тем же `read_verdict`, а не второй регуляркой: сверка, читающая прозу иначе,
    чем импорт, проверяет саму себя, а не перенос.
    """
    return {
        on: read_verdict(path.read_text(encoding="utf-8"))
        for on, path in collect_summaries(root)
    }


async def _known_days(db: AsyncSession) -> list[date]:
    """Все даты, у которых есть строка `day`, по возрастанию."""
    result = await db.execute(select(Day.day_date).order_by(Day.day_date))
    return list(result.scalars().all())


async def _summaries(db: AsyncSession) -> dict[date, tuple[str | None, str]]:
    """Вердикт и источник каждого сохранённого итога."""
    result = await db.execute(
        select(DaySummary.day_date, DaySummary.verdict, DaySummary.source)
    )
    return {row.day_date: (row.verdict, row.source) for row in result}


async def backfill(db: AsyncSession, *, root: Path | None = None) -> BackfillReport:
    """
    Довести уже импортированные дни до состояния, в котором «не закрывали» выразимо.

    Заводит `day` на каждую дату между первым и последним известным днём и
    больше ничего не пишет. Повторный прогон поэтому не пишет вовсе: дыр в
    календаре после первого не остаётся.
    """
    report = BackfillReport()
    known = await _known_days(db)
    if not known:
        return report

    have = set(known)
    current, last = known[0], known[-1]
    while current <= last:
        if current not in have:
            await day_crud.ensure_day(db, current)
            report.days_created.append(current)
        current += timedelta(days=1)
    await db.flush()

    stored = await _summaries(db)
    for on in await _known_days(db):
        found = stored.get(on)
        if found is None:
            report.open_days.append(on)
            continue
        verdict, source = found
        if verdict is None:
            report.unjudged.append(on)
        elif source == SOURCE_IMPORT and verdict == VERDICT_WON:
            report.migrated_won.append(on)
        elif source == SOURCE_IMPORT and verdict == VERDICT_LOST:
            report.migrated_lost.append(on)

    if root is not None:
        report.checked_against_files = True
        report.mismatches = _compare(verdicts_from_files(root), stored)
    return report


def _compare(
    files: dict[date, str | None], stored: dict[date, tuple[str | None, str]]
) -> list[Mismatch]:
    """
    Сверка по датам: что говорят файлы против того, что лежит в базе.

    Сравниваются вердикты, а не количество квадратов: «жёлтых столько же»
    сходится и тогда, когда две даты поменялись местами.
    """
    mismatches: list[Mismatch] = []
    for on in sorted(set(files) | set(stored)):
        in_files = files.get(on)
        row = stored.get(on)
        in_db = None if row is None else row[0]
        if in_files != in_db:
            mismatches.append(Mismatch(day_date=on, in_files=in_files, in_db=in_db))
    return mismatches


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.imports.day_stage_backfill",
        description=(
            "Довести уже импортированные дни до четвёртого состояния «не "
            "закрывали». Вердиктов не трогает ни одного."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Записать. Без флага прогон сухой и транзакция откатывается",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Явное умолчание: посчитать и напечатать, не записывая",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Каталог personal-os: сверить вердикты базы с summaries/**/*.md",
    )
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> BackfillReport:
    root: Path | None = None
    if args.root is not None:
        root = args.root.expanduser().resolve()
        if not root.is_dir():
            raise SystemExit(f"нет каталога {root}")
    async with AsyncSessionLocal() as session:
        # Границу дня публикует таблица правил; в свежем процессе её никто ещё
        # не читал, а `ensure_day` замораживает вид дня по правилу на дату.
        await day_crud.list_rules(session)
        report = await backfill(session, root=root)
        report.applied = args.apply
        if args.apply:
            await session.commit()
        else:
            await session.rollback()
        return report


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа `python -m app.imports.day_stage_backfill`."""
    args = _parse_args(argv)
    report = asyncio.run(_run(args))
    for line in report.as_lines():
        print(line)
    for mismatch in report.mismatches:
        print(mismatch.as_line())
    return 1 if report.mismatches else 0


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
