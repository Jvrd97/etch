# [review:need-review] PHASE-03/223, PHASE-03/245, PHASE-03/246, PHASE-03/251, PHASE-03/244
# summary: orchestration of the health advice — the prompt is rendered from the finished summary (no database, no recomputation), carries supplement names but never doses, forbids diagnoses and doses, and the not-medical-advice disclaimer is appended in code when the model omits it
"""
The words of the health advice (`#223`).

**Модель получает цифры, а не базу.** The prompt is rendered from the finished
`HealthSummaryResponse`, so a figure in the advice is the figure the summary
shows. The layer reads no table and computes nothing.

**Что модели не отдаём.** Дозы и единицы доз не уходят вообще: модель, видевшая
«200 мг», склонна его комментировать, а дозы назначать нельзя. Названия добавок
уходят — без них совет не про то, что человек пьёт, — и только в промпт на время
запроса: ни в лог, ни в базу.

**Оговорка не зависит от модели.** «Это не медицинская рекомендация» дописывает
код, если модель её не написала: правило безопасности не должно держаться на
послушности промпту.
"""

from __future__ import annotations

import re

from app.llm.client import LLMClient, LLMError
from app.llm.dose_guard import names_a_dose
from app.llm.health_format import average_basis, comparison_text, health_value
from app.schemas.supplement_advice import Adherence, HealthFigure, HealthSummaryResponse


class DoseGuardTripped(LLMError):
    """The model's answer names a dose; the answer is dropped, the error carries none of it."""


NOT_MEDICAL_ADVICE = "Это не медицинская рекомендация."
# «не медицинская рекомендация», «не является медицинской рекомендацией» и т.п.
_DISCLAIMER = re.compile(
    r"не\s+(?:является\s+)?медицинск\w*\s+(?:рекомендаци\w*|совет\w*)",
    re.IGNORECASE,
)
HEALTH_ADVICE_SYSTEM_PROMPT = """\
Ты помощник личного трекера привычек. Тебе дают цифры о движении, пульсе покоя
и приёме добавок за последние дни и за столько же дней до них. Напиши совет
по-русски: 3-5 коротких предложений обычным текстом без заголовков и списков.

Правила:
- Опирайся только на цифры из данных и называй конкретные: «в среднем 8000 шагов,
  на 1000 больше, чем раньше». Ничего не выдумывай и не округляй иначе.
- Если по блоку написано «данных нет» или «данных мало», не делай по нему выводов:
  скажи об этом одной фразой или промолчи.
- Не ставь диагнозов и не объясняй цифры болезнями.
- Не назначай дозировок и не советуй начинать, бросать или менять добавки и их
  количество: с этим идут к врачу.
- Совет — про привычки: регулярность приёма, движение, режим. Заверши одним
  конкретным действием на ближайшие дни."""


def _figure_line(figure: HealthFigure, days: int) -> str:
    if not figure.available or not figure.days_with_data:
        return f"{figure.name}: данных нет."
    if not figure.enough_data:
        return f"{figure.name}: данных мало ({figure.days_with_data} дн. из {days})."
    comparison = comparison_text(
        figure.key,
        figure.unit,
        figure.delta_avg_per_day,
        figure.previous_days_with_data,
        days,
        "к прошлому окну",
    )
    return (
        f"{figure.name}: в среднем "
        f"{health_value(figure.key, figure.unit, figure.avg_per_day or 0)} в день, "
        f"{average_basis(figure.days_with_data, days)} "
        f"({comparison})."
    )


def _one_line(text: str) -> str:
    """A name on a single line: a newline in it would pose as a line of the data."""
    return " ".join(text.split())


def adherence_lines(adherence: Adherence, window_days: int) -> list[str]:
    """The supplements as plain lines: names and counts, never a dose."""
    if not adherence.planned:
        return ["Добавки: данных нет."]
    if not adherence.enough_data:
        planned_days = sum(1 for day in adherence.days if day.planned)
        return [f"Добавки: данных мало ({planned_days} дн. из {window_days})."]
    lines = [
        f"Добавки: принято {adherence.taken} из {adherence.planned} "
        f"запланированных приёмов ({adherence.pct}%)."
    ]
    lines += [
        f"«{_one_line(item.name)}»: {item.taken_days} из {item.planned_days} дн."
        for item in adherence.supplements
    ]
    return lines


def summary_lines(summary: HealthSummaryResponse) -> list[str]:
    """
    The window and every figure of the summary as plain lines of numbers.

    The advice prompt and the chat card both print the summary through this one
    function, so a number the model is told in chat is the number the advice is
    written from.
    """
    window = summary.window
    lines = [
        f"Окно: {window.starts_on} - {window.ends_on}, {window.days} дн. "
        f"(сегодняшний день не входит). Сравнение: {window.previous_starts_on} - "
        f"{window.previous_ends_on}.",
    ]
    lines += [_figure_line(figure, window.days) for figure in summary.figures]
    lines += adherence_lines(summary.adherence, window.days)
    return lines


def build_health_advice_prompt(summary: HealthSummaryResponse) -> str:
    """The instruction plus the window as plain lines of numbers."""
    return (
        HEALTH_ADVICE_SYSTEM_PROMPT
        + "\n\nДанные:\n"
        + "\n".join(summary_lines(summary))
    )


def with_disclaimer(text: str) -> str:
    """The text, closed by the disclaimer unless the model already wrote it."""
    text = text.strip()
    if _DISCLAIMER.search(text):
        return text
    return f"{text}\n\n{NOT_MEDICAL_ADVICE}"


async def write_health_advice(llm: LLMClient, summary: HealthSummaryResponse) -> str:
    """
    The advice with its disclaimer.

    `LLMError` from the client is the caller's; so is `DoseGuardTripped` (an
    `LLMError` too, so a caller that does not care still catches it) raised here
    when the answer names a dose: such an answer is not shown, and the error text
    carries no part of it.
    """
    text = await llm.generate(build_health_advice_prompt(summary))
    if names_a_dose(text):
        raise DoseGuardTripped("the model named a dose")
    return with_disclaimer(text)
