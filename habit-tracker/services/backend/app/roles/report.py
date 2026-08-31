# [review:need-review] PHASE-03/138
# summary: render_summary_md — the block of the Friday report as finished text: a line per role with minutes, share and the gap from the target, `unassigned` beside them rather than under «прочее», the acts counted by kind, and the sentence that says the markup rules have fallen behind
"""
Пятничный отчёт как готовый текст.

**Рендер на сервере, а не в компоненте.** Тот же блок нужен скиллу `/day-close`
и будущему воркеру, и вторая реализация форматирования разъедется с первой на
первой же правке целевых долей — молча, потому что сверять текст в отчёте с
текстом на экране никто не станет.

**Числа в тексте — те же, что в JSON, до знака.** Здесь ничего не считается:
всё приезжает готовым из `app.crud.role.role_summary`. Единственное, что этот
модуль решает, — как их назвать по-русски. Это и делает пункт приёмки
проверяемым тестом, а не сверкой глазами.

**Целевая доля подписана гипотезой прямо в тексте.** Экран, называющий её
нормой, врёт про её природу — и текст, вставленный в отчёт руководству,
врал бы так же, только дальше.

**`unassigned` идёт строкой наравне с ролями.** Спрятанная в «прочее», она
перестаёт быть сигналом, а она — единственный признак того, что правила
разметки отстали: неверное правило разложит месяц неправильно и само сигнала
не подаст.
"""

from __future__ import annotations

from app.crud.role import UNASSIGNED_LAG_PCT, RolePeriodSlice, RoleSummary
from app.models.role import ROLE_CODE_FALLBACK

# Заголовок блока. Отчёт руководству человек пишет своими словами — блок отдаёт
# ему числа одним куском, и заголовок говорит, что это именно они.
TITLE = "## Роли за период"

# Что печатается вместо таблицы, когда за период не записано ни минуты.
# Формулировка несущая: «нет записей» и «ноль процентов CTO» — разные
# утверждения, и второе было бы измерением, которого не было.
NO_DATA_LINE = "Записей за период нет."

# Подпись целевых долей. Стоит в тексте, а не только на экране: блок уезжает в
# отчёт целиком, и подпись обязана уехать вместе с числом.
TARGET_NOTE = "Целевые доли — гипотеза квартала, а не норма: день по ним не судится."

# Заголовок части про акты.
ACTS_TITLE = "### Акты по видам"

# Что печатается, когда за период не закрыто ни одного акта.
NO_ACTS_LINE = "Актов за период нет."

# Сигнал к пересмотру. Назван заранее и в ADR-0020, и здесь: доля `unassigned`
# выше порога значит, что автоматику разметки надо выключать в пользу ручного
# ввода — чинить правила полдня в неделю дороже, чем не иметь их.
LAG_LINE = (
    "Правила разметки отстали: `unassigned` за {days} дней — {share}% "
    "(порог {threshold}%). По ADR-0020 автоматику разметки пора выключать "
    "в пользу ручного ввода."
)


def _hours(minutes: int) -> str:
    """Минуты часами и минутами — так их читает человек."""
    return f"{minutes // 60} ч {minutes % 60} мин"


def _delta(slice_: RolePeriodSlice) -> str:
    """Отклонение от целевой доли со знаком, либо прочерк — цели нет."""
    if slice_.delta_pct is None:
        return "—"
    return f"{slice_.delta_pct:+d} п.п."


def _target(slice_: RolePeriodSlice) -> str:
    """Целевая доля роли, либо прочерк."""
    if slice_.target_share_pct is None:
        return "—"
    return f"{slice_.target_share_pct}%"


def _role_line(slice_: RolePeriodSlice) -> str:
    """Одна строка таблицы ролей."""
    return (
        f"| {slice_.title} | {_hours(slice_.minutes)} | {slice_.share_pct}% "
        f"| {_target(slice_)} | {_delta(slice_)} |"
    )


def _acts_lines(summary: RoleSummary) -> list[str]:
    """Акты по ролям и видам; роль без актов в список не попадает."""
    lines: list[str] = []
    for slice_ in summary.roles:
        if slice_.act_total == 0:
            continue
        kinds = ", ".join(
            f"{kind} × {count}" for kind, count in sorted(slice_.act_counts.items())
        )
        lines.append(f"- **{slice_.title}** — {slice_.act_total}: {kinds}")
    return lines


def render_summary_md(summary: RoleSummary) -> str:
    """
    Свёртка периода готовым блоком Markdown.

    Вставляется в отчёт как есть: ни одного числа не приходится считать руками
    ни в голове, ни в калькуляторе. Именно поэтому здесь и минуты, и доля, и
    целевая, и отклонение — отклонение, которое пришлось бы вычитать самому,
    сделало бы блок наполовину готовым.
    """
    head = f"{TITLE} {summary.date_from.isoformat()} — {summary.date_to.isoformat()}"
    if summary.total_minutes == 0:
        return "\n\n".join([head, NO_DATA_LINE])

    working = [one for one in summary.roles if one.role_code != ROLE_CODE_FALLBACK]
    fallback = [one for one in summary.roles if one.role_code == ROLE_CODE_FALLBACK]

    table = [
        "| Роль | Минуты | Доля | Целевая | Отклонение |",
        "| --- | --- | --- | --- | --- |",
        *[_role_line(one) for one in working],
        # `unassigned` последней строкой той же таблицы, а не отдельным абзацем:
        # строка наравне с ролями — это и есть решение не прятать её в «прочее».
        *[_role_line(one) for one in fallback],
    ]

    blocks = [
        head,
        f"Всего за период: {_hours(summary.total_minutes)}.",
        "\n".join(table),
        TARGET_NOTE,
        ACTS_TITLE,
    ]
    acts = _acts_lines(summary)
    blocks.append("\n".join(acts) if acts else NO_ACTS_LINE)
    if summary.rules_lag:
        blocks.append(
            LAG_LINE.format(
                days=(summary.date_to - summary.window_from).days + 1,
                share=summary.window_unassigned_share_pct,
                threshold=UNASSIGNED_LAG_PCT,
            )
        )
    return "\n\n".join(blocks)


__all__ = [
    "ACTS_TITLE",
    "LAG_LINE",
    "NO_ACTS_LINE",
    "NO_DATA_LINE",
    "TARGET_NOTE",
    "TITLE",
    "render_summary_md",
]
