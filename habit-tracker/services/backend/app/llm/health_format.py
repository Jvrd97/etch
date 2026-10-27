# [review:need-review] PHASE-03/245, PHASE-03/239
# summary: the one Russian rendering of a health number for a prompt — unit words declined by the number, minutes as hours, a signed change, and the sentence that names the denominator of an average
"""
Числа здоровья словами для промптов (`#245`).

Обзор недели и совет писали «7421 шагов» каждый своей копией. Здесь строка одна:
единица склоняется по числу («1 шаг», «2 шага», «5 шагов»), минуты читаются
часами, а среднее называет свой знаменатель — дни с данными, а не все дни окна.
"""

from __future__ import annotations

from app.core.humanize import hours_and_minutes

__all__ = ["average_basis", "health_value", "plural_form", "signed_health_delta"]

MINUTES_UNIT = "min"
NO_DELTA_TEXT = "нет данных для сравнения"

# Числа, на которых окончание не следует последней цифре: 11-14 — всегда «-ов».
_TEEN_FROM = 11
_TEEN_TO = 14
_TENS = 10
_HUNDREDS = 100
_FEW_FROM = 2
_FEW_TO = 4

# Три формы слова: 1 шаг, 2 шага, 5 шагов. Неизменяемая единица — одно слово.
_UNIT_FORMS: dict[str, tuple[str, str, str]] = {
    "steps": ("шаг", "шага", "шагов"),
    "resting_hr": ("уд/мин", "уд/мин", "уд/мин"),
}


def plural_form(count: float, one: str, few: str, many: str) -> str:
    """
    Форма слова при числе `count`: «1 шаг», «2 шага», «5 шагов», «11 шагов».

    Дробное число управляет родительным падежом единственного числа («7421.5
    шага»), как и в обычной речи.
    """
    if count != int(count):
        return few
    whole = abs(int(count))
    if _TEEN_FROM <= whole % _HUNDREDS <= _TEEN_TO:
        return many
    last = whole % _TENS
    if last == 1:
        return one
    if _FEW_FROM <= last <= _FEW_TO:
        return few
    return many


def health_value(key: str, unit: str | None, value: float) -> str:
    """Число со словом единицы по-русски: «7421 шаг», «7 ч 10 мин», «60 уд/мин»."""
    if unit == MINUTES_UNIT:
        return hours_and_minutes(round(value))
    forms = _UNIT_FORMS.get(key)
    word = plural_form(value, *forms) if forms else (unit or "")
    return f"{value:g} {word}".strip()


def signed_health_delta(key: str, unit: str | None, delta: float | None) -> str:
    """Изменение среднего со знаком; нуль знака не имеет, пустота — словами."""
    if delta is None:
        return NO_DELTA_TEXT
    sign = "+" if delta > 0 else "-" if delta < 0 else ""
    return sign + health_value(key, unit, abs(delta))


def average_basis(days_with_data: int, days: int) -> str:
    """
    Знаменатель среднего, названный словами.

    Среднее делится на дни с данными: день без записи — это «данных нет», а не
    «ноль шагов» и не «ноль минут тренировки». Модель должна знать это, иначе
    «0 ч 30 мин в день» при двух днях из семи она прочтёт как половину часа
    ежедневно.
    """
    return f"среднее по дням с данными: {days_with_data} из {days} дн."
