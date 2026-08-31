# [review:need-review] PHASE-03/priemka-5.7
# summary: hours_and_minutes() — the one rendering of a duration as «N ч M мин»; the verdict clause and the Friday report each carried their own copy, one of them with 60 written into the string
"""
Числа продолжительности словами.

Одна строка, но написанная дважды, — это две строки, которые разъедутся молча:
человек читает клауз переработки и блок пятничного отчёта как один язык, и
правка формулировки в одном месте оставила бы второе на старой.
"""

from __future__ import annotations

# Сколько минут в часе. Названо, потому что продолжительность читается человеком
# в часах, а не в минутах.
MINUTES_PER_HOUR = 60


def hours_and_minutes(minutes: int) -> str:
    """Минуты часами и минутами — так их читает человек, а не «500 мин»."""
    return f"{minutes // MINUTES_PER_HOUR} ч {minutes % MINUTES_PER_HOUR} мин"
