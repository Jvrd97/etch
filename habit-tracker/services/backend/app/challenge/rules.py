# [review:need-review] PHASE-03/127
# summary: the vocabulary of a challenge (four rule kinds, three verdicts, two sources) and `verdict_for_day` — the pure answer to «этот день сделан», where a day nobody recorded is a miss rather than «нет данных»
"""
Правило челленджа и вердикт одного его дня.

Модуль чистый: он не знает ни про сессию, ни про таблицы, и ровно поэтому все
интересные случаи — четыре вида правила, пустой день, сегодняшний день —
проверяются без базы.

**Пустой день — промах, а не «нет данных».** Это единственное, чем челлендж
отличается от стрика по существу. У стрика день без записей чистый: человек
просто не курил и ничего не отмечал. У обязательства неподтверждённый день не
сделан — иначе «7 дней подряд ≥ 2 л воды» выполняется молчанием. Поэтому
`compute_streak` здесь не переиспользуется, а `is_relapse_value`
переиспользуется: «что такое сорвавшееся значение» остаётся одним правилом на
двух потребителей, а «что такое пустой день» у них разное намеренно.

**Сегодня промахом не бывает.** Пока локальные сутки не закрылись, у дня ещё
есть шанс: он либо уже `done`, либо `pending`. Промахом он становится, когда
`local_date()` назовёт следующее число, — та же граница суток, что у плана и у
вердикта дня, а не полночь UTC.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from app.crud.streak import is_relapse_value
from app.crud.values import is_true_value, parse_number
from app.models.field import FieldType

# Что именно обещано. Составные правила («и вода, и зал») вынесены из скоупа
# ADR-0018 явно: два обязательства — это два челленджа, и заваливаются они
# по отдельности.
RULE_METRIC_AT_LEAST = "metric_at_least"
RULE_METRIC_AT_MOST = "metric_at_most"
RULE_CHECKED = "checked"
RULE_ABSTAIN = "abstain"
RULE_KINDS: tuple[str, ...] = (
    RULE_METRIC_AT_LEAST,
    RULE_METRIC_AT_MOST,
    RULE_CHECKED,
    RULE_ABSTAIN,
)

# Виды, которым нужен порог: без него `≥` не с чем сравнивать. У `checked` и
# `abstain` порога нет, и присланный порог — ошибка, а не украшение.
METRIC_RULE_KINDS: tuple[str, ...] = (RULE_METRIC_AT_LEAST, RULE_METRIC_AT_MOST)

Verdict = Literal["done", "miss", "pending"]

VERDICT_DONE: Verdict = "done"
VERDICT_MISS: Verdict = "miss"
VERDICT_PENDING: Verdict = "pending"
VERDICTS: tuple[Verdict, ...] = (VERDICT_DONE, VERDICT_MISS, VERDICT_PENDING)

# Кто поставил вердикт. `manual` пересчёт не перетирает — см. `app.crud.challenge`.
SOURCE_COMPUTED = "computed"
SOURCE_MANUAL = "manual"
CHALLENGE_DAY_SOURCES: tuple[str, ...] = (SOURCE_COMPUTED, SOURCE_MANUAL)

# Потолок окна. Обязательство длиной в год — это не обязательство, а образ
# жизни, и мерить его надо не промахами по дням; плюс ленивая материализация
# держит в памяти ровно столько дней, сколько в окне.
MAX_CHALLENGE_DAYS = 92


@dataclass(frozen=True)
class ChallengeRule:
    """Обещание одной строкой: какого вида и с каким порогом."""

    kind: str
    target: Decimal | None


@dataclass(frozen=True)
class DaySample:
    """
    Что известно про один день челленджа.

    `has_entry` отдельно от `values`, потому что запись без значения в нужном
    поле — это всё-таки запись, а вот день, в который человек не открыл трекер,
    ничем не подтверждён.
    """

    has_entry: bool
    values: tuple[str | None, ...]


def sum_values(values: tuple[str | None, ...]) -> Decimal:
    """
    Сумма числовых значений дня.

    Сумма, а не максимум: два стакана по литру — это два литра. Нечисловой
    текст `parse_number` уже отбросил с предупреждением в лог, здесь он просто
    не участвует.
    """
    total = Decimal(0)
    for value in values:
        number = parse_number(value)
        if number is not None:
            total += Decimal(str(number))
    return total


def verdict_for_day(
    rule: ChallengeRule,
    field_type: FieldType,
    sample: DaySample,
    *,
    is_closed: bool,
) -> Verdict:
    """
    Вердикт одного дня челленджа.

    `is_closed` — закрылись ли локальные сутки этого дня. Незакрытый день не
    промахивается: он либо уже выполнен, либо ждёт. Кто отвечает на вопрос
    «какое сегодня число», модуль не решает — это `app.core.daytime.local_date`,
    и вызывающий приносит ответ сюда готовым.
    """
    if _is_satisfied(rule, field_type, sample):
        return VERDICT_DONE
    return VERDICT_MISS if is_closed else VERDICT_PENDING


def _is_satisfied(
    rule: ChallengeRule, field_type: FieldType, sample: DaySample
) -> bool:
    """Выполнено ли обещание в этот день по тому, что о нём записано."""
    if not sample.has_entry:
        return False

    if rule.kind == RULE_ABSTAIN:
        # Ровно тот же предикат, которым живёт стрик avoid-категории: числа на
        # карточке челленджа и на карточке стрика не должны спорить.
        return not any(is_relapse_value(field_type, value) for value in sample.values)

    if rule.kind == RULE_CHECKED:
        return any(is_true_value(value) for value in sample.values)

    if rule.target is None:
        # Схема этого не пропускает; здесь — чтобы вид с порогом без порога не
        # превращался молча в «выполнено».
        return False

    total = sum_values(sample.values)
    if rule.kind == RULE_METRIC_AT_LEAST:
        return total >= rule.target
    if rule.kind == RULE_METRIC_AT_MOST:
        return total <= rule.target
    return False
