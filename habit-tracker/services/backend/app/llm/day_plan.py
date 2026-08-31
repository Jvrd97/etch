# [review:need-review] PHASE-03/148
# summary: the model half of plan generation — the prompt built from the canon row and derived flags (never a complaint's text), the parse whose error message carries loc and type but no input, the eight constraints run over the answer, and a repair prompt made of rule codes and item codes and nothing else
"""
Генерация плана моделью: промпт, разбор, ремонт.

**Промпт собран из канона, а не из переписки.** Строка `day_rule_set` даёт края
дня, потолки и свободный вечер; сигналы дня приезжают производными флагами вида
`training_gate: no_overhead_press`. Текста жалобы на тело в промпте нет — не
только из приватности: генератору симптом не нужен, ему нужно ограничение, и
лишний личный текст в промпте это риск без выгоды.

**Ремонтный заход ровно один.** Модель, ошибившаяся дважды на одном и том же,
не сходится, а каждый лишний круг — это ожидание человека и второй вызов.
Второй провал уходит наверх, и оркестрация из `app/day/generate.py` пишет
скелет.

**Ремонтный промпт не цитирует ответ.** Он состоит из кодов нарушенных правил и
кодов строк-нарушителей. Это отличается от `plan_flow.build_repair_prompt`,
который вкладывает предыдущий ответ целиком, — и отличается намеренно: строка
плана бывает названа диагнозом, а промпт уходит наружу.
"""

from __future__ import annotations

import json
from datetime import date

from pydantic import ValidationError

from app.day import skeleton
from app.day.constraints import Violation, check_all
from app.llm.client import LLMClient
from app.llm.plan_flow import PlanError, extract_json, generate_with_repair
from app.models.day import DayRuleSet
from app.schemas.day_plan import GeneratedDayPlan, to_draft

DAY_PLAN_PROMPT = """\
You lay out one day as a plan, from the canon given below.

You emit ONLY a JSON object, no prose, no markdown fences, of the shape:
{
  "title": "<short title of the day>",
  "sections": [
    {
      "title": "<section title>",
      "kind": "anchors|training|hard_points|work|study|evening|personal|queue|free|other",
      "items": [
        {
          "code": "<short handle: W1, подъём>",
          "kind": "bullet|step|table_row|task|anchor|hard_point|minimum",
          "rigidity": "hard|soft|free",
          "text": "<what the person reads>",
          "window": "HH:MM-HH:MM or null",
          "done_criterion": "<required on a task>",
          "unlinked_reason": "<why a task has no quarter goal>"
        }
      ]
    }
  ]
}

Rules of the canon, all of them checked after you answer:
- Only the edges of the day may be `rigidity: "hard"` — every other line is
  `soft`, and lines of the free block are `free` and carry no window.
- The free evening stays empty. Do not put work in it.
- The measured work of the day must fit under the ceiling, and the number of
  work tasks must not exceed the cap.
- The health anchors of the canon come before work starts.
- Windows must not overlap, and every line belongs to the target day only.
- Every line needs its own `code`; the same code twice is an error.
- Output must be valid JSON and nothing else."""

# Флаг ограничения тренировки — производная от жалоб, а не их текст.
TRAINING_GATE_PREFIX = "training_gate"


class DayPlanError(PlanError):
    """Ответ модели не разобрался или нарушил канон."""


def _canon(target: date, rule: DayRuleSet) -> str:
    """Канон дня как строки промпта: края, потолки, свободный вечер."""
    return "\n".join(
        [
            f"- target_day: {target.isoformat()}",
            f"- timezone: {rule.timezone}",
            f"- day_start_hour: {rule.day_start_hour}",
            f"- wake_at: {rule.wake_at}",
            f"- work_start: {rule.work_start}",
            f"- work_stop_at: {rule.work_stop_at}",
            f"- review_at: {rule.review_at}",
            f"- bedtime_max: {rule.bedtime_max}",
            f"- work_cap_min: {rule.work_cap_min}",
            f"- work_hard_cap_min: {rule.work_hard_cap_min}",
            f"- max_work_tasks: {rule.max_work_tasks}",
            f"- free_evening: {rule.free_evening_start}..{rule.free_evening_end}",
            f"- required_anchors: {', '.join(rule.required_anchors) or 'none'}",
            f"- hard_edge_kinds: {', '.join(rule.hard_edge_kinds) or 'none'}",
        ]
    )


def _signal_lines(signals: skeleton.Signals, gates: tuple[str, ...]) -> str:
    """
    Что известно о дне сверх строки канона — флагами, не текстом.

    Жалоба на тело доезжает сюда как `training_gate: no_overhead_press`. Сам
    симптом остаётся в базе жалоб: генератору он не нужен, а промпт — это
    место, откуда личный текст утекает дальше всего.
    """
    lines = [f"- is_training_day: {str(signals.is_training_day).lower()}"]
    for gate in gates:
        lines.append(f"- {TRAINING_GATE_PREFIX}: {gate}")
    return "\n".join(lines)


def build_prompt(
    target: date,
    rule: DayRuleSet,
    signals: skeleton.Signals,
    gates: tuple[str, ...] = (),
) -> str:
    """Промпт целиком: правила ответа, канон дня, производные флаги."""
    return (
        f"{DAY_PLAN_PROMPT}\n\n"
        f"## Canon in force\n{_canon(target, rule)}\n\n"
        f"## Signals of the day\n{_signal_lines(signals, gates)}"
    )


def parse_plan(text: str) -> GeneratedDayPlan:
    """
    Сырой текст модели → план (проверка формы).

    Своя, а не `plan_flow.parse_json_plan`: сообщение об ошибке уходит в
    ремонтный промпт, а `ValidationError.errors()` кладёт в него `input` —
    то есть текст строки, которую модель придумала. Здесь остаются только
    путь до поля и вид ошибки.
    """
    try:
        payload = extract_json(text)
    except PlanError as exc:
        raise DayPlanError(str(exc)) from exc
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise DayPlanError(f"invalid JSON: {exc.msg}") from exc
    try:
        return GeneratedDayPlan.model_validate(data)
    except ValidationError as exc:
        shape = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['type']}"
            for error in exc.errors()
        )
        raise DayPlanError(f"plan does not match schema: {shape}") from exc


# Ключ, под которым правила складывают идентификаторы строк-нарушителей.
ITEM_IDS_KEY = "item_ids"


def _offending_codes(violation: Violation, codes: dict[str, str]) -> list[str]:
    """Строки-нарушители кодами, которыми их назвала сама модель."""
    ids = violation.detail.get(ITEM_IDS_KEY)
    if not isinstance(ids, list):
        return []
    return [codes.get(str(one), str(one)) for one in ids]


def violation_summary(violations: list[Violation], codes: dict[str, str]) -> str:
    """
    Нарушения строкой — кодами правил и кодами строк.

    Идентификаторы переводятся обратно в коды, потому что код модель писала
    сама и узнаёт его; uuid она не видела ни разу. Ни одного текста строки
    здесь нет и быть не может: `Violation.detail` его не носит.
    """
    parts: list[str] = []
    for violation in violations:
        named = _offending_codes(violation, codes)
        listed = ", ".join(named)
        parts.append(violation.rule_code + (f" [{listed}]" if listed else ""))
    return "; ".join(parts)


def build_repair(base_prompt: str, previous: str, error: str) -> str:
    """
    Ремонтный промпт: базовый промпт плюс коды. Предыдущий ответ не вкладывается.

    `previous` в подписи остаётся, потому что её задаёт `generate_with_repair`,
    но не используется: ответ модели — это текст плана, а он личный ровно в той
    же мере, что и всё остальное, что человек про свой день пишет.
    """
    return (
        f"{base_prompt}\n\n"
        f"## Your previous answer broke the canon\n{error}\n\n"
        "Codes in square brackets are the lines that broke each rule. "
        "Return a corrected JSON object for the whole day. JSON only."
    )


async def generate_day_plan(
    llm: LLMClient,
    target: date,
    rule: DayRuleSet,
    signals: skeleton.Signals,
    gates: tuple[str, ...] = (),
) -> GeneratedDayPlan:
    """
    План дня от модели, проверенный формой и каноном, с одним заходом ремонта.

    Проверка каноном стоит внутри `parse_and_validate`, а не после: иначе
    ремонтный заход чинил бы только сломанный JSON, а нарушение канона —
    самая частая из двух причин, по которым план не годится.
    """
    prompt = build_prompt(target, rule, signals, gates)

    def parse_and_validate(text: str) -> GeneratedDayPlan:
        plan = parse_plan(text)
        violations = check_all(to_draft(plan, target, rule), rule)
        if violations:
            raise DayPlanError(violation_summary(violations, plan.codes()))
        return plan

    return await generate_with_repair(llm, prompt, parse_and_validate, build_repair)
