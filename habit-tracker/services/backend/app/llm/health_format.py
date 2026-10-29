# [review:need-review] PHASE-03/245, PHASE-03/239, PHASE-03/255
# summary: the one Russian rendering of a health number for a prompt — unit words declined by the number, minutes as hours, a signed change, and the sentence that names the denominator of an average
"""
Числа здоровья словами для промптов (`#245`).

Обзор недели и совет писали «7421 шагов» каждый своей копией. Здесь строка одна:
единица склоняется по числу («1 шаг», «2 шага», «5 шагов»), минуты читаются
часами, а среднее называет свой знаменатель — дни с данными, а не все дни окна.
"""

from __future__ import annotations

import math

from app.core.humanize import hours_and_minutes

__all__ = [
    "average_basis",
    "comparison_text",
    "health_value",
    "plural_form",
    "signed_health_delta",
]

MINUTES_UNIT = "min"
NO_DELTA_TEXT = "нет данных для сравнения"

# Знаков после точки при печати числа: среднее за день округлено до одного,
# шесть — запас, чтобы печать не округляла тайком (111.96 остаётся «111.96»).
PRINTED_DIGITS = 6

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


def number_text(value: float) -> str:
    """
    Число так, как оно напечатано в промпте: без показателя степени и без хвоста нулей.

    «8000», «7421.5», «100000», «1000000»; `:g` дал бы «1e+06» и срезал бы шесть
    значащих цифр. Форму слова выбирает эта строка, а не исходное число.
    """
    if not math.isfinite(value):
        raise ValueError("a health value must be a finite number")
    text = f"{value:.{PRINTED_DIGITS}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def _plural_for_text(text: str, one: str, few: str, many: str) -> str:
    """Форма слова при числе, напечатанном как `text`; дробь — родительный единственного."""
    if "." in text:
        return few
    whole = abs(int(text))
    if _TEEN_FROM <= whole % _HUNDREDS <= _TEEN_TO:
        return many
    last = whole % _TENS
    if last == 1:
        return one
    if _FEW_FROM <= last <= _FEW_TO:
        return few
    return many


def plural_form(count: float, one: str, few: str, many: str) -> str:
    """
    Форма слова при числе `count`: «1 шаг», «2 шага», «5 шагов», «11 шагов».

    Считается по напечатанному числу (`number_text`): 111.9999999 печатается как
    «112», и это «112 шагов». Дробное число управляет родительным падежом
    единственного числа («7421.5 шага»), как и в обычной речи.
    """
    return _plural_for_text(number_text(count), one, few, many)


def health_value(key: str, unit: str | None, value: float) -> str:
    """Число со словом единицы по-русски: «7421 шаг», «7 ч 10 мин», «60 уд/мин»."""
    if unit == MINUTES_UNIT:
        return hours_and_minutes(round(value))
    text = number_text(value)
    forms = _UNIT_FORMS.get(key)
    word = _plural_for_text(text, *forms) if forms else (unit or "")
    return f"{text} {word}".strip()


def signed_health_delta(key: str, unit: str | None, delta: float | None) -> str:
    """Изменение среднего со знаком; нуль знака не имеет, пустота — словами."""
    if delta is None:
        return NO_DELTA_TEXT
    magnitude = abs(delta)
    # Знак ставится по напечатанному: «-0 шагов» читается как ошибка.
    prints_zero = (
        round(magnitude) == 0
        if unit == MINUTES_UNIT
        else not float(number_text(magnitude))
    )
    sign = "" if prints_zero else "+" if delta > 0 else "-"
    return sign + health_value(key, unit, magnitude)


def average_basis(days_with_data: int, days: int) -> str:
    """
    Знаменатель среднего, названный словами.

    Среднее делится на дни с данными: день без записи — это «данных нет», а не
    «ноль шагов» и не «ноль минут тренировки». Модель должна знать это, иначе
    «0 ч 30 мин в день» при двух днях из семи она прочтёт как половину часа
    ежедневно. Слово «среднее» тут не повторяется: фраза идёт после «в среднем».

    **Минуты тренировки.** День без сэмплов Apple Exercise Time не считается нулём.
    Часы без Watch и без синхронизации не пишут ничего, и отсутствие записи не
    отличить от дня без тренировки; нуль превратил бы пробел в «упало».
    """
    return f"по дням с данными: {days_with_data} из {days} дн."


def comparison_text(
    key: str,
    unit: str | None,
    delta: float | None,
    previous_days_with_data: int,
    days: int,
    against: str,
) -> str:
    """
    Изменение среднего и база прошлого окна: «+1000 шагов к прошлому окну, против 5 из 7 дн.».

    Разница двух средних честна, только если известно, сколько дней стоит за
    каждым: среднее по двум дням прошлой недели и по семи днём этой — не одно и то же.
    """
    if delta is None:
        return NO_DELTA_TEXT
    change = signed_health_delta(key, unit, delta)
    return f"{change} {against}, против {previous_days_with_data} из {days} дн."
