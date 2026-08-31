# [review:need-review] PHASE-03/115
# summary: pulling a plan out of a chat answer — the fenced JSON block is found in prose, parsed through `app.llm.plan_flow`, and one repair round is asked for; a plan that still does not parse leaves the turn standing as an ordinary message with no card
"""
План из ответа чата.

**Невалидный план не роняет ход.** Реплика человека уже записана, ответ модели
уже прочитан, и отказ парсера — это отсутствие плашки, а не ошибка разговора.
Поэтому все функции здесь возвращают `None` вместо исключения наружу: единственный
способ, которым сломанный JSON может испортить ход, — если кто-то решит его
пробросить.

**Ремонтный заход ровно один.** Модель, ответившая мимо схемы дважды подряд, не
сходится, а каждый лишний круг — это ещё одно ожидание человека. Правило то же,
что у `generate_with_repair` в `app.llm.plan_flow`, и взято оттуда, а не
придумано здесь.

**Блока нет — ремонта нет.** Ответ без JSON-блока означает, что модели нечего
было предложить: это самый частый случай в разговоре, и просить её «починить»
отсутствие плана значило бы платить лишним вызовом за каждую вторую реплику.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable

from app.llm.plan_flow import PlanError, extract_json, parse_json_plan
from app.schemas.chat import ChatPlan

logger = logging.getLogger(__name__)

# Маркер, по которому ответ признаётся несущим план. Не просто «есть фигурная
# скобка»: модель цитирует JSON в объяснениях, и каждая такая цитата иначе
# уходила бы в ремонтный вызов.
PLAN_MARKER = '"plan"'

# Как просят починить. Инструкция короткая нарочно: длинная воспроизводила бы
# схему словами, а схема и так приезжает в промпте один раз.
REPAIR_INSTRUCTION = (
    "Твой прошлый JSON-план не прошёл проверку схемы. Причина ниже. "
    'Верни исправленный объект вида {"plan": {...}} и ничего кроме него.'
)


class ChatPlanError(PlanError):
    """Ответ чата, из которого не удалось достать план по схеме."""


def carries_plan(text: str) -> bool:
    """Похоже ли, что ответ вообще что-то предлагает записать."""
    return PLAN_MARKER in text


def parse_plan(text: str) -> ChatPlan:
    """
    Достать план из ответа, форма и схема.

    Обёртка над общим `parse_json_plan`: тот умеет и в заборчик из тройных
    кавычек, и в прозу вокруг объекта. Здесь добавлено одно — план лежит под
    ключом `plan`, а не в корне, чтобы модель могла ответить человеку словами и
    приложить предложение рядом.
    """
    payload = _plan_object(text)
    return parse_json_plan(payload, ChatPlan, ChatPlanError)


def _plan_object(text: str) -> str:
    """Кусок ответа, который должен быть планом."""
    try:
        raw = extract_json(text)
    except ValueError as exc:
        raise ChatPlanError(str(exc)) from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ChatPlanError(f"invalid JSON: {exc.msg}") from exc

    if not isinstance(data, dict) or "plan" not in data:
        raise ChatPlanError("the JSON object carries no `plan` key")
    return json.dumps(data["plan"])


async def plan_from_answer(
    text: str,
    *,
    repair: Callable[[str], Awaitable[str]] | None = None,
) -> ChatPlan | None:
    """
    План, который несёт ответ модели, или `None`.

    `repair` — способ задать модели ровно один дополнительный вопрос. Он
    необязателен: тест, оффлайновый разбор и путь без бэкенда обходятся без
    него, и отсутствие ремонта — это на один план меньше, а не отказ.

    Ни текст ответа, ни причина отказа в лог не идут: и то и другое может нести
    и промпт, и слова человека. В логе остаётся факт.
    """
    if not carries_plan(text):
        return None

    try:
        return parse_plan(text)
    except ChatPlanError as first_error:
        if repair is None:
            logger.info("chat plan rejected, no repair pass configured")
            return None
        try:
            repaired = await repair(
                f"{REPAIR_INSTRUCTION}\n\n## Причина\n{first_error}"
            )
            return parse_plan(repaired)
        except ChatPlanError:
            logger.info("chat plan rejected twice, the turn stands without a card")
            return None
