# [review:need-review] PHASE-03/221, PHASE-03/245, PHASE-03/239
# summary: orchestration of the week narrative — the prompt is built from the already computed review (no recomputation, no database), and the model is reached only through LLMClient.generate
"""
The words of the week review (`#221`).

**Модель получает цифры, а не базу.** The prompt is rendered from the finished
`WeekReviewResponse`, so a figure in the text is the figure on the screen. The
layer reads no table and computes nothing: a second count here would be the
version of «сколько дней выиграно» that disagrees with the first.

**Что модели не отдаём.** Названия окон и содержимое записей в обзоре не
попадают вообще; уходят названия категорий и ролей, числа и даты. Здоровье
подаётся числами, и промпт запрещает диагнозы и дозировки.
"""

from __future__ import annotations

from datetime import date

from app.core.humanize import hours_and_minutes
from app.llm.client import LLMClient
from app.llm.health_format import average_basis, health_value, signed_health_delta
from app.schemas.week_review import WeekReviewResponse

WEEK_REVIEW_SYSTEM_PROMPT = """\
Ты помощник личного трекера привычек. Тебе дают цифры одной недели и прошлой
недели за столько же дней. Напиши итог недели по-русски: 4-6 коротких
предложений обычным текстом без заголовков и списков.

Правила:
- Опирайся только на цифры из данных, ничего не выдумывай и не округляй иначе.
- Начни с главного: строка «Неделя выиграна» в данных — готовый вердикт, повтори
  его и не пересуживай по своим правилам; затем сравни с прошлой неделей.
- Назови лучший и худший день, если они есть в данных, и одну заметную
  разницу в ролях, категориях или здоровье.
- Если неделя не закончилась, скажи об этом прямо и не делай выводов о ней
  целиком.
- Если по какому-то блоку данных нет, не упоминай его.
- Не ставь диагнозов, не назначай дозировок и не давай медицинских советов:
  здоровье упоминай только как цифры.
- Заверши одним конкретным действием на следующую неделю."""

_WEEKDAYS = (
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
)


def _weekday(review: WeekReviewResponse, day: date) -> str:
    return _WEEKDAYS[next(d.weekday for d in review.days if d.date == day)]


def _outcome_line(review: WeekReviewResponse) -> str:
    """
    Вердикт недели готовой строкой: модель его не судит, а пересказывает.

    Правило одно — `week_is_won`, и считается оно на сервере: все дни выиграны,
    дни есть и долга за переработку нет. «5 из 6» — это «нет», а не «почти».
    """
    if review.is_won is None:
        return "Неделя выиграна: пока не решено, неделя идёт."
    totals = review.totals
    return (
        f"Неделя выиграна: {'да' if review.is_won else 'нет'} "
        f"(правило: выиграны все дни недели и нет долга за переработку; "
        f"выиграно {totals.won_days} из {totals.days_total} дней, "
        f"долг {review.debt_minutes} мин)."
    )


def _signed(value: int | float | None, suffix: str = "") -> str:
    if value is None:
        return "нет данных для сравнения"
    return f"{value:+g}{suffix}"


def build_week_review_prompt(review: WeekReviewResponse) -> str:
    """The instruction plus the week as plain lines of numbers."""
    window, totals, delta = review.window, review.totals, review.delta
    lines = [
        f"Неделя {window.iso_code}: {window.starts_on} - {window.ends_on}.",
    ]
    if window.is_complete:
        lines.append("Неделя закончилась.")
    else:
        lines.append(
            f"Неделя не закончилась: учтено дней {window.counted_days} из 7, "
            f"прошлая неделя взята за те же {window.compared_days}."
        )
    lines += [
        _outcome_line(review),
        f"Выиграно дней: {totals.won_days} из {totals.closed_days} закрытых "
        f"(прошлая неделя: {review.previous_totals.won_days} из "
        f"{review.previous_totals.closed_days}).",
        f"Задачи плана: {totals.tasks_done} из {totals.tasks_total}"
        + (f", {totals.plan_pct}%" if totals.plan_pct is not None else "")
        + f"; разница с прошлой неделей {_signed(delta.plan_pct, ' п.п.')}.",
    ]
    if totals.work_minutes is not None:
        lines.append(
            f"Рабочее время: {hours_and_minutes(totals.work_minutes)}; "
            f"разница с прошлой {_signed(delta.work_minutes, ' мин')}."
        )
    if review.best_day is not None:
        lines.append(
            f"Лучший день: {_weekday(review, review.best_day)} {review.best_day}."
        )
    if review.worst_day is not None:
        lines.append(
            f"Худший день: {_weekday(review, review.worst_day)} {review.worst_day}."
        )
    for role in (r for r in review.roles if r.minutes or r.previous_minutes):
        lines.append(
            f"Роль {role.title}: {hours_and_minutes(role.minutes)}, {role.share_pct}% "
            f"({_signed(role.delta_minutes, ' мин')} к прошлой неделе)."
        )
    for category in review.categories:
        lines.append(
            f"Категория {category.name}: {hours_and_minutes(category.minutes)} "
            f"за {category.entry_days} дн. ({_signed(category.delta_minutes, ' мин')})."
        )
    for streak in review.habit_streaks:
        lines.append(
            f"Серия «{streak.name}»: {streak.current_streak} дн., срывов за неделю "
            f"{streak.relapses}."
        )
    for metric in (m for m in review.health if m.days_with_data):
        change = signed_health_delta(metric.key, metric.unit, metric.delta_avg_per_day)
        lines.append(
            f"{metric.name}: в среднем "
            f"{health_value(metric.key, metric.unit, metric.avg_per_day or 0)} в день, "
            f"{average_basis(metric.days_with_data, window.counted_days)} "
            f"({change} к прошлой неделе)."
        )
    return WEEK_REVIEW_SYSTEM_PROMPT + "\n\nДанные:\n" + "\n".join(lines)


async def write_week_review(llm: LLMClient, review: WeekReviewResponse) -> str:
    """The narrative of the week; `LLMError` from the client is left to the caller."""
    return (await llm.generate(build_week_review_prompt(review))).strip()
