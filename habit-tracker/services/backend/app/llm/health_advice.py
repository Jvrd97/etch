# [review:need-review] PHASE-03/223, PHASE-03/245, PHASE-03/246
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
from app.llm.health_format import average_basis, health_value, signed_health_delta
from app.schemas.supplement_advice import HealthFigure, HealthSummaryResponse

NOT_MEDICAL_ADVICE = "Это не медицинская рекомендация."
# «не медицинская рекомендация», «не является медицинской рекомендацией» и т.п.
_DISCLAIMER = re.compile(
    r"не\s+(?:является\s+)?медицинск\w*\s+(?:рекомендаци\w*|совет\w*)",
    re.IGNORECASE,
)
# A number glued to a dose unit: «200 мг», «1 г.», «400 миллиграммов», «5000 ед.»,
# «400 µg», «две капсулы». The model is told never to name one; this is the net
# under the instruction. `µ` is the micro sign (U+00B5), `μ` the Greek mu (U+03BC).
_DOSE_UNIT = (
    r"(?:мг|мкг|ме|iu|mg|mcg|[µμ]\s?[gг]|мл|ml|милли?грамм\w*|микро?грамм\w*|"
    r"грамм\w*|гр|ед(?:иниц\w*)?|таблет\w*|капсул\w*|[gг])"
)
# Bare «г» is also the abbreviation of «год»: «в 2026 г, когда…» is not a dose.
_YEAR_AS_YEARS = r"(?:19|20)\d{2}\s*[gг](?!\w)"
_NUMBER_WORDS = (
    r"(?:ноль|нуль|один|одна|одну|одно|одного|одной|два|две|двух|три|трёх|трех|"
    r"четыре|четырёх|четырех|пять|пяти|шесть|шести|семь|семи|восемь|восьми|"
    r"девять|девяти|десять|десяти|одиннадцать|двенадцать|тринадцать|четырнадцать|"
    r"пятнадцать|шестнадцать|семнадцать|восемнадцать|девятнадцать|двадцать|"
    r"тридцать|сорок|пятьдесят|шестьдесят|семьдесят|восемьдесят|девяносто|сто|"
    r"двести|триста|четыреста|пятьсот|шестьсот|семьсот|восемьсот|девятьсот|"
    r"тысяча|тысячи|тысяч|полтора|полторы)"
)
_DOSE = re.compile(
    rf"(?<![\d.,])(?!{_YEAR_AS_YEARS})\d+(?:[.,]\d+)?\s*{_DOSE_UNIT}(?!\w)"
    rf"|\b{_NUMBER_WORDS}\s+{_DOSE_UNIT}(?!\w)",
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
    delta = signed_health_delta(figure.key, figure.unit, figure.delta_avg_per_day)
    return (
        f"{figure.name}: в среднем "
        f"{health_value(figure.key, figure.unit, figure.avg_per_day or 0)} в день, "
        f"{average_basis(figure.days_with_data, days)} "
        f"({delta} к предыдущим {days} дн.)."
    )


def _one_line(text: str) -> str:
    """A name on a single line: a newline in it would pose as a line of the data."""
    return " ".join(text.split())


def _adherence_lines(summary: HealthSummaryResponse) -> list[str]:
    adherence = summary.adherence
    if not adherence.planned:
        return ["Добавки: данных нет."]
    if not adherence.enough_data:
        planned_days = sum(1 for day in adherence.days if day.planned)
        return [f"Добавки: данных мало ({planned_days} дн. из {summary.window.days})."]
    lines = [
        f"Добавки: принято {adherence.taken} из {adherence.planned} "
        f"запланированных приёмов ({adherence.pct}%)."
    ]
    lines += [
        f"«{_one_line(item.name)}»: {item.taken_days} из {item.planned_days} дн."
        for item in adherence.supplements
    ]
    return lines


def build_health_advice_prompt(summary: HealthSummaryResponse) -> str:
    """The instruction plus the window as plain lines of numbers."""
    window = summary.window
    lines = [
        f"Окно: {window.starts_on} - {window.ends_on}, {window.days} дн. "
        f"(сегодняшний день не входит). Сравнение: {window.previous_starts_on} - "
        f"{window.previous_ends_on}.",
    ]
    lines += [_figure_line(figure, window.days) for figure in summary.figures]
    lines += _adherence_lines(summary)
    return HEALTH_ADVICE_SYSTEM_PROMPT + "\n\nДанные:\n" + "\n".join(lines)


def with_disclaimer(text: str) -> str:
    """The text, closed by the disclaimer unless the model already wrote it."""
    text = text.strip()
    if _DISCLAIMER.search(text):
        return text
    return f"{text}\n\n{NOT_MEDICAL_ADVICE}"


async def write_health_advice(llm: LLMClient, summary: HealthSummaryResponse) -> str:
    """
    The advice with its disclaimer.

    `LLMError` from the client is the caller's; so is the one raised here when the
    answer names a dose: such an answer is not shown, and the error text carries
    no part of it.
    """
    text = await llm.generate(build_health_advice_prompt(summary))
    if _DOSE.search(text):
        raise LLMError("the model named a dose")
    return with_disclaimer(text)
