# [review:need-review] PHASE-03/139
# summary: the seam between «что размечаем» and «чем размечаем» — historical samples of the automatic sources rebuilt from the rows those sources wrote, so a rule can be tried against real history before it is saved and a period can be marked up again after it is
"""
Что правило разметки видит, когда его прогоняют по истории.

**Именованный шов, а не заглушка.** Настоящий источник образцов — интервалы
активности мака (`#155`) и дневные сигналы коммитов и ClickUp (`#146`) — ещё не
приехал. До него единственное, что история о себе помнит, — строки, которые
автоматические источники уже записали: `role_time_block` и `role_act` с
`source` из `app_usage`, `git` и `clickup`. Из них образец восстановим: заголовок
акта — это сообщение коммита или имя задачи, записка блока — то, чем его
подписал импортёр.

Когда `activity_interval` приедет, меняется ровно одна функция —
`historical_samples`, — и ни сухой прогон, ни переразметка про это не узнают.
Ровно затем шов и назван: без него обе они читали бы таблицы напрямую, и приезд
настоящего источника стоил бы переписывания трёх модулей вместо одного.

**Восстановленный образец беднее настоящего, и это сказано вслух.** У блока
`app_usage` нет ни `bundle_id`, ни заголовка окна отдельно от записки: строка
несёт то, что несла. Поэтому `scanned_rows` едет наружу вместе со счётчиками —
ноль совпадений на нулевой истории и ноль совпадений на месяце данных это разные
ответы, и второй читается как «правило не ловит», а первый — нет.

**Заголовки окон отсюда не логируются.** По ADR-0020 B5 это чувствительная
строка: имя документа, корреспондент, потенциально идентификатор пациента. Она
сравнивается и уезжает в примеры на экран человека, но не в лог.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.role import (
    SOURCE_APP_USAGE,
    SOURCE_CLICKUP,
    SOURCE_GIT,
    RoleAct,
    RoleTimeBlock,
)
from app.roles.matcher import MatchSample

# Источники, которые размечает правило. Ручной ввод сюда не входит и не войдёт:
# роль, выбранная человеком, правилом не переписывается — это то же решение B4,
# что защищает `confidence='confirmed'`.
AUTOMATIC_SOURCES: tuple[str, ...] = (SOURCE_APP_USAGE, SOURCE_GIT, SOURCE_CLICKUP)

# Что означает строка в таблицах фактов: минуты или акт. Наружу едет как есть —
# «сколько интервалов и актов зацепило правило» это два числа, а не одно.
KIND_TIME_BLOCK = "time_block"
KIND_ACT = "act"


@dataclass(frozen=True)
class HistoricalSample:
    """
    Одна строка истории вместе с образцом, по которому её размечали.

    `row_id` и `kind` нужны переразметке — она пишет обратно в ту же строку;
    `role_id` и `rule_id` — отчёту «до/после»; `label` — примерам на экране.
    `confirmed` решает, трогать ли строку вообще.
    """

    kind: str
    row_id: int
    work_day: date
    role_id: int
    rule_id: int | None
    confirmed: bool
    label: str
    sample: MatchSample


def _sample_of(source: str, text: str) -> MatchSample:
    """
    Образец из того, что несёт строка.

    Один текст на три поля намеренно: восстановленная строка не знает, чем она
    была — сообщением коммита, именем задачи или заголовком окна, — и правило
    любого из трёх видов обязано получить свой шанс совпасть. Настоящий источник
    (`#155`, `#146`) раскладывает это по полям сам, и тогда здесь останется
    один разбор вместо трёх присваиваний.
    """
    return MatchSample(
        source=source,
        window_title=text or None,
        commit_message=text or None,
        clickup_list=text or None,
        repo_path=text or None,
    )


async def historical_samples(
    db: AsyncSession, date_from: date, date_to: date
) -> list[HistoricalSample]:
    """
    Всё, что автоматические источники записали за период, с образцами.

    Обе границы включительно. Ручные строки не попадают сюда вовсе: правило их
    не размечало и не будет.
    """
    samples: list[HistoricalSample] = []

    blocks = await db.execute(
        select(RoleTimeBlock)
        .where(
            RoleTimeBlock.source.in_(AUTOMATIC_SOURCES),
            RoleTimeBlock.work_day >= date_from,
            RoleTimeBlock.work_day <= date_to,
        )
        .order_by(RoleTimeBlock.id)
    )
    for block in blocks.scalars().all():
        text = block.note or ""
        samples.append(
            HistoricalSample(
                kind=KIND_TIME_BLOCK,
                row_id=block.id,
                work_day=block.work_day,
                role_id=block.role_id,
                rule_id=block.rule_id,
                confirmed=block.confidence == "confirmed",
                label=text,
                sample=_sample_of(block.source, text),
            )
        )

    acts = await db.execute(
        select(RoleAct)
        .where(
            RoleAct.source.in_(AUTOMATIC_SOURCES),
            RoleAct.work_day >= date_from,
            RoleAct.work_day <= date_to,
        )
        .order_by(RoleAct.id)
    )
    for act in acts.scalars().all():
        samples.append(
            HistoricalSample(
                kind=KIND_ACT,
                row_id=act.id,
                work_day=act.work_day,
                role_id=act.role_id,
                # Акт `rule_id` не носит: у таблицы такой колонки нет, и
                # «каким правилом размечен» у него читается только через роль.
                rule_id=None,
                confirmed=act.confidence == "confirmed",
                label=act.title,
                sample=_sample_of(act.source, act.title),
            )
        )

    return samples


__all__ = [
    "AUTOMATIC_SOURCES",
    "KIND_ACT",
    "KIND_TIME_BLOCK",
    "HistoricalSample",
    "historical_samples",
]
