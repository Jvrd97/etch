# [review:need-review] PHASE-03/115, PHASE-03/189
# summary: pulling a plan out of a chat answer — the fenced JSON block is found in prose, parsed through `app.llm.plan_flow`, and one repair round is asked for; a plan that still does not parse leaves the turn standing as an ordinary message with no card
# summary: PHASE-03/189 counts braces instead of taking the span between the outermost ones, and picks the LAST object carrying a `plan` key — an answer holding a second object no longer parses as broken JSON and loses the card silently
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

from app.llm.plan_flow import PlanError, parse_json_plan
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


def _json_objects(text: str) -> list[str]:
    """
    Каждый сбалансированный объект `{...}` в тексте, в порядке появления.

    Скобки считаются, а не ищутся крайние: общий `extract_json` берёт кусок от
    первой открывающей до последней закрывающей во всём тексте, и на ответе с
    двумя объектами это даёт span, внутри которого проза. Разбор такого span
    падает молча — плашки просто нет, и по ответу модели не видно почему.

    Скобка внутри строкового литерала не считается: `"text": "план на {день}"`
    — законная строка плана, а не начало объекта. Экранирование учитывается по
    той же причине.
    """
    found: list[str] = []
    depth = 0
    start = -1
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth > 0:
            depth -= 1
            if depth == 0:
                found.append(text[start : index + 1])
    return found


def _plan_object(text: str) -> str:
    """
    Кусок ответа, который должен быть планом.

    Берётся **последний** объект, несущий ключ `plan`. Последний, а не первый:
    модель цитирует чужой JSON, отвечает про прошлый заход и объясняет схему
    словами, и предложение стоит в конце ответа — там, где его и просит промпт.
    Объект без ключа `plan` не заслоняет собой тот, в котором план есть.
    """
    candidates = _json_objects(text)
    if not candidates:
        raise ChatPlanError("no JSON object found in the response")

    reason = "the JSON object carries no `plan` key"
    for raw in reversed(candidates):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            reason = f"invalid JSON: {exc.msg}"
            continue
        if isinstance(data, dict) and "plan" in data:
            return json.dumps(data["plan"])
    raise ChatPlanError(reason)


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
