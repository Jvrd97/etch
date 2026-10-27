# [review:need-review] PHASE-03/251
# summary: the phrase sets of the dose net — pharmacy abbreviations, case forms of number words, fractions, Latin units, invisible characters, a number glued to a comma — and the phrases that must pass (dates, steps, percents, pulse)
"""
The dose net of the health advice (`#251`).

The model is told never to name a dose; `names_a_dose` is the net under that
instruction. Two sets: what must be caught (the forms a pharmacy and a person
write) and what must pass (a net that trips on «в 3 местах» costs the person the
advice). Every case is a parameter, so a miss names the phrase.
"""

import time
import unicodedata

import pytest

from app.llm.dose_guard import names_a_dose

# Linear in practice: 30 000 characters of groups took 1.4 s when it was quadratic.
SLOW_INPUT_SECONDS = 0.5

CAUGHT = [
    # units after a digit
    "Пей магний по 400 мг на ночь.",
    "Пей 400мг.",
    "Пей 400 МГ.",
    "Добавь 5000 МЕ витамина D.",
    "Добавь 5000 ME витамина D.",
    "Добавь 5000 IU витамина D.",
    "Add 5000 iu daily.",
    "Take 200 mg daily.",
    "Take 200mg daily.",
    "Take 50 mcg daily.",
    "Take 1 g daily.",
    "Take 400 µg daily.",
    "Take 400 μg daily.",
    "Take 400 ug daily.",
    "Пей 400 μг.",
    "Пей 400 мкг.",
    "Пей 400 мкг утром.",
    "Хватит 1,5 г в день.",
    "Хватит 1.5 г в день.",
    "Хватит 1 г.",
    "Хватит 2 гр.",
    "Хватит 2 грамм.",
    "Хватит 2 грамма.",
    "Хватит 5 граммов.",
    "Хватит 0,5 грамма.",
    "Налей 5 мл.",
    "Налей 5 ml.",
    "Пей по 400 миллиграммов.",
    "Пей по 400 миллиграмм.",
    "Пей по 400 милиграмм.",
    "Пей по 400 милиграммов.",
    "Пей по 400 миллиграмов.",
    "Пей по 400 микрограммов.",
    "Пей по 50 микрограмм.",
    "Добавь 5000 ед.",
    "Добавь 5000 единиц витамина D.",
    "Добавь 1 единицу.",
    # pharmacy abbreviations and thousands
    "Добавь 5 тыс. МЕ витамина D.",
    "Добавь 5 тыс МЕ витамина D.",
    "Добавь 5 тыс. ед.",
    "Добавь 5 тысяч МЕ.",
    "Добавь 5 тысяч единиц.",
    "Добавь 10 000 МЕ.",
    "Добавь 10 000 мг.",
    "Выпей 1 табл.",
    "Выпей 1 табл. утром.",
    "Выпей 2 таб.",
    "Выпей 2 капс.",
    "Выпей 2 капс. на ночь.",
    "Выпей 2 капсулы утром.",
    "Выпей 3 таблетки.",
    "Выпей 1 таблетку.",
    "Выпей 10 капель.",
    "Выпей 5 капли.",
    "Выпей 1 ампулу.",
    # number words in every case
    "Выпей две капсулы утром.",
    "Выпей одну капсулу.",
    "Выпей одну таблетку.",
    "Выпей двумя капсулами.",
    "Запивай двумя капсулами.",
    "Начни с двух капсул.",
    "Дели по трём таблеткам.",
    "Дели по трем таблеткам.",
    "Дели по трёх таблеток.",
    "Пей по четыре таблетки.",
    "Пей по четырём таблеткам.",
    "Пей четырьмя таблетками.",
    "Пей пять таблеток.",
    "Пей пятью таблетками.",
    "Пей десять капсул.",
    "Пей двадцать капсул.",
    "Пей по шести капсул.",
    "Хватит одного грамма.",
    "Пей четыреста миллиграммов.",
    "Пей четырёхсот миллиграммов.",
    "Пей пятьсот мг.",
    "Пей двести мкг.",
    "Добавь пять тысяч единиц.",
    "Добавь пять тысяч МЕ.",
    "Выпей полторы таблетки.",
    "Выпей полтора грамма.",
    "Выпей сто миллиграммов.",
    # fractions
    "Выпей полтаблетки.",
    "Выпей полтаблетку.",
    "Выпей пол-таблетки.",
    "Выпей полкапсулы.",
    "Выпей половину таблетки.",
    "Выпей половину капсулы.",
    "Выпей половинку таблетки.",
    "Выпей четверть таблетки.",
    "Выпей четвертинку таблетки.",
    "Выпей треть капсулы.",
    "Выпей ½ таблетки.",
    "Выпей 1/2 таблетки.",
    "Выпей ¼ таблетки.",
    "Выпей 0,5 таблетки.",
    # the endings -ой / -ей / -ою, which a careless fold eats («й» -> «и»)
    "Пей по одной таблетке.",
    "Пей по одной капсуле.",
    "Выпей одной капсулой.",
    "Запей 1 таблеткой.",
    "Запей 1 капсулой.",
    "Выпей одной таблетки.",
    "Капни одной каплей.",
    "Вколи 1 ампулой.",
    "Рассоси 1 пилюлей.",
    "Добавь одной единицей.",
    "Хватит двух граммов.",
    "Хватит одним граммом.",
    # decomposed and invisible characters
    "Дели по трёх таблеток.",
    "Пей 4​00 мг.",
    "Пей 400​ мг.",
    "Пей 400 м​г.",
    "Пей 400 мил­ли­грамм.",
    "Пей 4‍00 мг.",
    "Пей 400⁠мг.",
    "Пей 400 мг.",
    "Пей 400 мг.",
    "Пей ４００ мг.",
    # glued to a comma or a dot
    "Утром,400 мг.",
    "Утром.400 мг.",
    "Утром:400 мг.",
    "Пей магний,2 капсулы.",
    "Пей магний,две капсулы.",
    # mixed alphabets
    "Пей 400 мg.",
    "Пей 400 mг.",
    "Пей 400 mкг.",
    # a year-like number is a dose when the unit is not the year
    "Пей 2000 мг.",
    "Пей 2000 МЕ.",
    "Хватит 2000 грамм.",
    "Хватит 1,500 г.",
]

PASSED = [
    # words that only begin like a unit
    "Это грамотно.",
    "Это было грамотное решение.",
    "Мгновение спустя ты ходил больше.",
    "В 3 местах пульс был выше.",
    "Три места, где ты ходил больше.",
    "В 3 мелких шагах.",
    "Ты прошёл 3 единственных километра.",
    "Выпей воды, 2 таблицы данных ниже.",
    "Пять таблиц с данными.",
    "Два капитана одной команды.",
    "Три гражданина.",
    "Таблетницу держи на виду.",
    "Капсулы держи на виду.",
    "Принимай добавки регулярно.",
    "Одна таблетница на неделю.",
    # numbers that are not doses
    "15%, а не 10%.",
    "Пульс 60 уд/мин.",
    "Пульс покоя 60 уд/мин, на 4 уд/мин ниже.",
    "10 000 шагов в день.",
    "10 000 шагов — хорошая цель.",
    "8000 шагов в день.",
    "На 1000 шагов больше, чем раньше.",
    "30 минут тренировки.",
    "Тренировка 0 ч 30 мин в день.",
    "Спи 7 ч 30 мин.",
    "Три дня подряд и пять тысяч шагов.",
    "Принято 5 из 7 запланированных приёмов (71%).",
    "Среднее по дням с данными: 5 из 7 дн.",
    "7 дн. из 14.",
    "За 14 дней ты ходил больше.",
    "Сделай 2 прогулки.",
    "Выбери 3 дня на этой неделе.",
    "Два раза в неделю.",
    "Пять дней подряд.",
    # years and dates
    "Было так в 2026 г, когда ты ходил меньше.",
    "Было так в 2026 г., когда ты ходил меньше.",
    "С 01.12.2026 г. ты ходил больше.",
    "С 12.2026 г. ты ходил больше.",
    "В 2025–2026 гг. ты ходил больше.",
    "В 2025-2026 гг. ты ходил больше.",
    "К 20 октября 2026 г. ты ходил больше.",
    "8000 шагов в день и 60 уд/мин в покое, на 3 дня чаще, чем в 2026 г.",
    "В 1999 г, когда ты ходил меньше.",
    # the data lines of the prompt, echoed by the model
    "Шаги: в среднем 8000 шагов в день, по дням с данными: 7 из 7 дн. (+1000 шагов к прошлому окну, против 7 из 7 дн.).",
    "Окно: 2026-10-20 - 2026-10-26, 7 дн. (сегодняшний день не входит).",
    "Добавки: принято 5 из 7 запланированных приёмов (71%).",
    "Совет: пройдись вечером и отметь приём в одно и то же время.",
    # «единица» is also a point of a measure that is not a dose
    "Пульс покоя снизился на 4 единицы.",
    "Пульс покоя ниже на две единицы.",
    "Пульс упал на 3 ед.",
    "Пульс покоя вырос на одну единицу, а шагов стало больше.",
    "Пульс покоя 58 уд/мин — на 4 единицы ниже, чем неделей раньше.",
    "Пульс покоя 58 уд/мин, на 4 ед. ниже, чем неделей раньше.",
]

# Dose and a pulse in one text: only the unit after the pulse words is not a dose.
CAUGHT_NEXT_TO_A_PULSE = [
    "Пульс снизился. Пей 5000 ед.",
    "Пульс снизился, добавь 5000 единиц витамина D.",
    "Пульс 60, добавь пять тысяч единиц.",
    "Пульс снизился на 4 единицы. Добавь 5000 МЕ.",
    # the pulse and the dose in one clause, with no «на» before the number
    "При пульсе выше 100 принимай 5000 ед",
    "Пульс в норме и 5000 ед витамина D хватит",
    "Пульс в норме (5000 ед. витамина D хватит)",
    "Пульс в норме,5000 ед",
    "Сердцебиение частое 2000 ед",
    "С пульсом всё в порядке 2000 ед д3 подойдёт",
    # «на» does not make a thousand of units a point of the pulse
    "Пульс снизился на 5 тыс. ед.",
    "Пульс ниже, добавь на 5 тысяч единиц",
]


@pytest.mark.parametrize("text", CAUGHT)
def test_a_dose_is_caught(text: str) -> None:
    assert names_a_dose(text), text


@pytest.mark.parametrize("text", PASSED)
def test_a_plain_phrase_passes(text: str) -> None:
    assert not names_a_dose(text), text


def test_the_sets_are_large_enough_to_mean_something() -> None:
    assert len(CAUGHT) + len(PASSED) >= 120


def test_a_text_without_digits_or_units_is_quick() -> None:
    """The net runs on every answer: a long text must not make it crawl."""
    assert not names_a_dose("слово " * 20_000)
    assert not names_a_dose("1 " * 20_000)


def test_a_run_of_thousands_groups_does_not_make_the_net_quadratic() -> None:
    started = time.perf_counter()
    assert not names_a_dose("1" + " 000" * 6_000)
    assert time.perf_counter() - started < SLOW_INPUT_SECONDS


@pytest.mark.parametrize("text", CAUGHT_NEXT_TO_A_PULSE)
def test_a_dose_next_to_a_pulse_is_still_caught(text: str) -> None:
    assert names_a_dose(text), text


# Written by hand, apart from the patterns: the case is a class of error — a fold
# that eats an ending shows up as a hole in one column of this table, not in a phrase.
NUMERALS = [
    "ноль", "нуль",
    "один", "одна", "одно", "одну", "одной", "одного", "одному", "одним",
    "два", "две", "двух", "двум", "двумя",
    "три", "трёх", "трем", "тремя",
    "четыре", "четырёх", "четырем", "четырьмя",
    "пять", "пяти", "пятью", "шесть", "шести", "шестью",
    "семь", "семи", "семью", "восемь", "восьми", "восемью",
    "девять", "девяти", "девятью", "десять", "десяти", "десятью",
    "одиннадцать", "двенадцати", "тринадцатью", "четырнадцать",
    "пятнадцати", "шестнадцать", "семнадцати", "восемнадцать", "девятнадцати",
    "двадцать", "двадцати", "двадцатью", "тридцать", "тридцати",
    "сорок", "сорока", "пятьдесят", "пятидесяти", "шестьдесят", "шестидесяти",
    "семьдесят", "семидесяти", "восемьдесят", "восьмидесяти",
    "девяносто", "девяноста", "сто", "ста",
    "двести", "двухсот", "триста", "трёхсот", "четыреста", "четырёхсот",
    "пятьсот", "пятисот", "шестьсот", "шестисот", "семьсот", "семисот",
    "восемьсот", "восьмисот", "девятьсот", "девятисот",
    "тысяча", "тысячи", "тысяч", "полтора", "полторы", "полутора",
]  # fmt: skip


def _forms(stem: str, endings: str) -> list[str]:
    return [stem + ending for ending in endings.split(",")]


UNIT_FORMS = [
    *_forms("таблетк", "а,и,у,е,ой,ою"), "таблеток", "таблеткам", "таблетками", "таблетках",
    *_forms("капсул", "а,ы,у,е,ой,ою,ам,ами,ах"), "капсул",
    *_forms("капл", "я,и,ю,е,ей,ею,ям,ями,ях"), "капель",
    *_forms("ампул", "а,ы,у,е,ой,ою,ам,ами,ах"), "ампул",
    *_forms("пилюл", "я,и,ю,е,ей,ею,ям,ями,ях"), "пилюль",
    *_forms("единиц", "а,ы,у,е,ей,ею,ам,ами,ах"), "единиц", "ед.",
    *_forms("грамм", "а,ов,у,ом,е,ы,ам,ами,ах"), "грамм", "гр.",
    *_forms("миллиграмм", "а,ов,у,ом,е,ы,ам,ами,ах"), "миллиграмм",
    *_forms("микрограмм", "а,ов,у,ом,е,ы,ам,ами,ах"), "микрограмм",
    "мг", "мкг", "МЕ", "IU", "mg", "mcg", "мл", "ml", "капс.", "табл.", "таб.",
]  # fmt: skip

SHAPES = {
    "plain": lambda text: text,
    "decomposed": lambda text: unicodedata.normalize("NFD", text),
    "capitalised": lambda text: text.capitalize(),
    "shouted": lambda text: text.upper(),
    "no-break-space": lambda text: text.replace(" ", "\u00a0"),
}


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("unit", UNIT_FORMS)
def test_every_numeral_before_every_unit_form_is_a_dose(unit: str, shape: str) -> None:
    """Each unit form after each numeral, plain and decomposed: no ending may be lost."""
    missed = [
        phrase
        for numeral in NUMERALS
        if not names_a_dose(phrase := SHAPES[shape](f"Выпей {numeral} {unit}"))
    ]
    assert not missed, missed


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("unit", UNIT_FORMS)
def test_a_digit_before_every_unit_form_is_a_dose(unit: str, shape: str) -> None:
    assert names_a_dose(SHAPES[shape](f"Выпей 5 {unit}")), unit
    assert names_a_dose(SHAPES[shape](f"Выпей 1,5 {unit}")), unit
