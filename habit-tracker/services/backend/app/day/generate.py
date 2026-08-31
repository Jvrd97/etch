# [review:need-review] PHASE-03/148
# summary: the orchestration of one generation — at most two model calls inside a 120-second-per-call and 300-second-total budget, and a skeleton written under `fallback` with a reason code whenever the model is missing, slow, broken or wrong twice; the day is never left without a plan
"""
Оркестрация генерации плана: попытка, ремонт, скелет.

**День без плана не остаётся никогда.** Модель не настроена, упала, не уложилась
в бюджет, второй раз нарушила канон — во всех четырёх случаях пишется скелет с
`source='fallback'` и кодом причины. `failed` остаётся только на случай, когда
не записался и скелет: это отказ базы, а не отказ модели.

**Бюджет считается здесь, а не в клиенте.** У клиента свой таймаут на вызов
(120 секунд), но два вызова подряд плюс проверки — это уже не «один вызов», и
человек, нажавший кнопку, ждёт всё вместе. Общий потолок — 300 секунд, и по
его исчерпании пишется скелет, а не 504.

**Логируется только то, что не текст.** Код причины, число вызовов, дата. Ни
плана, ни строки, ни отчёта, ни жалобы.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date

from app.day import skeleton
from app.day.constraints import ORIGIN_AI, ORIGIN_FALLBACK, Violation, check_all
from app.llm.client import LLMClient, LLMError
from app.llm.day_plan import DayPlanError, generate_day_plan
from app.models.day import DayRuleSet
from app.crud.plan_violation import skeleton_document
from app.schemas.day_plan import to_document, to_draft
from app.schemas.plan import PlanDocument

logger = logging.getLogger(__name__)

# Кем собран план. Совпадает со значением, которое ложится в `day_plan.source`.
AUTHOR_LLM = "llm"
AUTHOR_FALLBACK = "fallback"

# Почему собран скелет. Коды, а не предложения: их читает и экран, и тест.
REASON_LLM_NOT_CONFIGURED = "llm_not_configured"
REASON_LLM_ERROR = "llm_error"
REASON_LLM_TIMEOUT = "llm_timeout"
REASON_PLAN_INVALID = "llm_plan_invalid"

# Потолок на всю генерацию: две попытки модели плюс проверки. Клиент держит
# свои 120 секунд на вызов, но ждёт человек всё вместе.
TOTAL_BUDGET_SECONDS = 300.0
# Потолок на один вызов. Дублирует таймаут клиента намеренно: клиент
# конфигурируется настройками и подменяется в тестах, а обещание «один вызов не
# длиннее двух минут» — свойство этого пути.
CALL_BUDGET_SECONDS = 120.0


class _TimedClient(LLMClient):
    """
    Клиент с потолком на один вызов.

    Обёртка, а не настройка внутри клиента: реализаций клиента две (API и CLI),
    в тестах стоит третья, и обещание «один вызов не длиннее двух минут» — это
    свойство пути генерации, а не каждой из них по отдельности.
    """

    def __init__(self, inner: LLMClient, budget: float = CALL_BUDGET_SECONDS) -> None:
        self._inner = inner
        self._budget = budget
        self.model = inner.model

    async def generate(self, prompt: str) -> str:
        return await asyncio.wait_for(
            self._inner.generate(prompt), timeout=self._budget
        )


@dataclass(frozen=True)
class GeneratedPlan:
    """
    Готовый документ и происхождение: кем собран и, если скелетом, почему.

    Причина — это код, а не сообщение: её кладут в базу, показывают на экране
    дня и сверяют в тесте, и три разных предложения об одном и том же были бы
    тремя разными состояниями.
    """

    document: PlanDocument
    author: str
    reason: str | None
    # Нарушения последнего ответа модели — то, из-за чего писался скелет.
    # Пустой список у плана, который прошёл, и у отказа не про канон.
    violations: tuple[Violation, ...] = ()

    @property
    def origin(self) -> str:
        """Чьи нарушения писать в `plan_violation`."""
        return ORIGIN_AI if self.author == AUTHOR_LLM else ORIGIN_FALLBACK


def _skeleton(
    target: date,
    rule: DayRuleSet,
    signals: skeleton.Signals,
    reason: str,
    violations: tuple[Violation, ...] = (),
) -> GeneratedPlan:
    """Скелет как результат генерации, с кодом причины."""
    built = skeleton.skeleton_plan(target, rule, signals=signals)
    document = skeleton_document(built, rule)
    # Скелет пишется под своим авторством, а не под тем, которым его назвал
    # `skeleton_document`: причина, по которой день собран не моделью, — часть
    # состояния дня, и она обязана быть видна из строки плана.
    document.source = AUTHOR_FALLBACK
    logger.info("day %s: plan assembled by fallback, reason %s", target, reason)
    return GeneratedPlan(
        document=document,
        author=AUTHOR_FALLBACK,
        reason=reason,
        violations=violations,
    )


async def generate_plan(
    llm: LLMClient | None,
    target: date,
    rule: DayRuleSet,
    signals: skeleton.Signals | None = None,
    gates: tuple[str, ...] = (),
) -> GeneratedPlan:
    """
    Собрать план на `target`: моделью, если получится, скелетом — если нет.

    Ни одна ветка не поднимает исключение наружу. Отсутствие модели — не
    состояние дня: человек, у которого кончилась подписка, не остаётся без
    плана и не видит 503 там, где ждал день.
    """
    resolved = signals if signals is not None else skeleton.Signals()

    if llm is None:
        return _skeleton(target, rule, resolved, REASON_LLM_NOT_CONFIGURED)

    try:
        plan = await asyncio.wait_for(
            generate_day_plan(_TimedClient(llm), target, rule, resolved, gates),
            timeout=TOTAL_BUDGET_SECONDS,
        )
    except asyncio.TimeoutError:
        return _skeleton(target, rule, resolved, REASON_LLM_TIMEOUT)
    except DayPlanError:
        # Второй ответ снова не годится. Сообщение сюда не тащится: оно ушло в
        # ремонтный промпт и там же кончилось, а в состоянии дня остаётся код.
        return _skeleton(target, rule, resolved, REASON_PLAN_INVALID)
    except LLMError:
        return _skeleton(target, rule, resolved, REASON_LLM_ERROR)

    # Проверка повторяется поверх принятого плана. Не из недоверия к
    # `generate_day_plan`, а потому что записывается именно этот документ, и
    # «проверено» обязано относиться к тому, что легло в базу.
    violations = tuple(check_all(to_draft(plan, target, rule), rule))
    if violations:
        return _skeleton(target, rule, resolved, REASON_PLAN_INVALID, violations)

    logger.info("day %s: plan assembled by the model", target)
    return GeneratedPlan(
        document=to_document(plan, AUTHOR_LLM), author=AUTHOR_LLM, reason=None
    )
