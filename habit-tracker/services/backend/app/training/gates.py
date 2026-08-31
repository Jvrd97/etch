# [review:need-review] PHASE-03/92
# summary: the five gates of `/train` over the state snapshot — an open complaint takes out what loads that area, 48 hours guard a heavy pattern, two near-failure days cap the week's intensity, sixteen sets close a pattern and two skipped days cut the volume of the return — all decided without a database so the skill and the page answer the same thing
"""
Гейты подбора тренировки, посчитанные над состоянием тела.

До `#92` эти пять правил жили прозой в `~/.claude/skills/train/SKILL.md`, и это
значило ровно одно: их выполнял тот, кто их прочитал. Страница дня не знала о
них ничего, а скилл проверял их по памяти — «плечо open, значит подтягиваний
нет» держалось на внимательности агента. Здесь они функция от снимка
состояния, и скилл со страницей отвечают одинаково по построению.

**Порядок жёсткий, и первый сработавший не отменяет остальные.** Жалоба
убирает движения, сорок восемь часов убирают паттерн, отказ и пропуски меняют
интенсивность и объём. Каждый сработавший гейт называет себя и причину: список
упражнений без объяснения — это ровно тот ответ, из-за которого предложение
тренировки читается как «нелогично».

**Жалоба сопоставляется областью, а не названием упражнения.** В `body_complaint`
человек пишет «левое плечо», в каталоге у упражнения стоит область «плечо».
Совпадение — вхождение кода области в текст жалобы; так «правое плечо» и
«плечо ноет» попадают в тот же гейт без словаря синонимов. Закрытие жалобы
возвращает движения тем же путём: снимок перестаёт называть область.

**Красный флаг сюда не помещается и не должен.** Ночная боль, слабость, потеря
амплитуды, щелчок — это «к врачу», а не «замени упражнение», и решение о том,
что это, принимает человек. Гейт умеет только снять нагрузку с области.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta

from app.models.training import (
    PATTERN_CARDIO,
    PATTERN_CORE,
    PATTERN_LEGS,
    PATTERN_PULL,
    PATTERN_PUSH,
)
from app.training.state import TrainingSnapshot

__all__ = [
    "CATALOGUE",
    "GATE_COMPLAINT",
    "GATE_HEAVY_48H",
    "GATE_NEAR_FAILURE",
    "GATE_RETURN",
    "GATE_WEEK_VOLUME",
    "HEAVY_GAP_DAYS",
    "NEAR_FAILURE_WEEK_LIMIT",
    "RETURN_VOLUME_FACTOR",
    "RIR_HARD",
    "RIR_RETURN",
    "RIR_SOFT",
    "SKIPPED_DAYS_LIMIT",
    "WEEK_SETS_LIMIT",
    "Exercise",
    "Excluded",
    "FiredGate",
    "Suggestion",
    "suggest",
]

# Which gate fired, machine-readable. The Russian a person reads is the
# `reason` beside it, the same split `mark.state` and `verdict_reason` use.
GATE_COMPLAINT = "complaint"
GATE_HEAVY_48H = "heavy_48h"
GATE_NEAR_FAILURE = "near_failure"
GATE_WEEK_VOLUME = "week_volume"
GATE_RETURN = "return_after_skips"

# Сорок восемь часов между тяжёлыми повторами паттерна. В днях, потому что
# `training_day` — строка на дату, а не отметка времени: «вчера» это разница в
# один день, и она меньше двух.
HEAVY_GAP_DAYS = 2

# Не больше двух near-failure дней за неделю суммарно. Выбрано — вся оставшаяся
# неделя в RIR 2-3, без исключений.
NEAR_FAILURE_WEEK_LIMIT = 2

# Потолок недельного объёма на паттерн. Рабочий ориентир канона — 12-20
# подходов на группу в неделю; шестнадцать это точка, после которой добавленный
# подход почти ничего не даёт, и паттерн уступает место другому.
WEEK_SETS_LIMIT = 16

# Два пропуска подряд — неделя не догоняется. Первый день после возврата идёт
# на RIR 3 и минус тридцать процентов объёма.
SKIPPED_DAYS_LIMIT = 2
RETURN_VOLUME_FACTOR = 0.7
FULL_VOLUME_FACTOR = 1.0

# Целевой запас до отказа. Три значения, а не число, потому что канон говорит
# диапазонами и человек читает именно их.
RIR_HARD = "RIR 1-2"
RIR_SOFT = "RIR 2-3"
RIR_RETURN = "RIR 3"


@dataclass(frozen=True)
class Exercise:
    """
    One movement of the catalogue: what it trains and what it loads.

    `areas` are area codes — «плечо», «поясница», — deliberately coarser than
    what a person writes into a complaint. Matching a coarse code against free
    text is what lets «левое плечо» and «плечо ноет» hit the same gate without a
    dictionary of synonyms nobody would maintain.
    """

    name: str
    pattern: str
    areas: tuple[str, ...] = ()


# Движения, которыми канон закрывает паттерны. Список тренировочный, а не
# исчерпывающий: подбор упражнений моделью — вне этого среза, здесь нужен
# набор, на котором гейты дают проверяемый ответ.
CATALOGUE: tuple[Exercise, ...] = (
    Exercise("подтягивания", PATTERN_PULL, ("плечо",)),
    Exercise("австралийские тяги", PATTERN_PULL, ()),
    Exercise("тяга гантели в наклоне", PATTERN_PULL, ()),
    Exercise("отжимания", PATTERN_PUSH, ()),
    Exercise("жим гантелей стоя", PATTERN_PUSH, ("плечо",)),
    Exercise("отжимания на брусьях", PATTERN_PUSH, ("плечо",)),
    Exercise("присед", PATTERN_LEGS, ("колено",)),
    Exercise("румынская тяга", PATTERN_LEGS, ("поясница",)),
    Exercise("болгарский сплит", PATTERN_LEGS, ("колено",)),
    Exercise("планка", PATTERN_CORE, ()),
    Exercise("скручивания", PATTERN_CORE, ("поясница",)),
    Exercise("ходьба или велосипед", PATTERN_CARDIO, ()),
)


@dataclass(frozen=True)
class FiredGate:
    """One gate that fired, and the sentence explaining what it did."""

    code: str
    reason: str


@dataclass(frozen=True)
class Excluded:
    """One movement that will not be suggested today, and by which gate."""

    exercise: str
    gate: str
    reason: str


@dataclass(frozen=True)
class Suggestion:
    """
    What may be trained today, what may not, and why — the whole answer.

    The exclusions travel beside the offer rather than being subtracted
    silently: «сегодня без подтягиваний, плечо open с 10.08» is a sentence a
    person can disagree with, and a shorter list with no explanation is the one
    that gets ignored.
    """

    exercises: tuple[str, ...]
    excluded: tuple[Excluded, ...]
    gates: tuple[FiredGate, ...]
    rir: str
    volume_factor: float


def _complaint_hits(exercise: Exercise, complaint: str) -> bool:
    """Whether an open complaint covers an area this movement loads."""
    lowered = complaint.casefold()
    return any(area.casefold() in lowered for area in exercise.areas)


def _blocked_by_complaints(exercise: Exercise, complaints: Sequence[str]) -> str | None:
    """The complaint that takes this movement out today, if any does."""
    for complaint in complaints:
        if _complaint_hits(exercise, complaint):
            return complaint
    return None


def _heavy_recently(snapshot: TrainingSnapshot, pattern: str) -> bool:
    """
    Whether `pattern` was trained heavy inside the 48-hour window.

    Only `pull` and `push` carry a «heavy» date of their own — those are the two
    the canon rotates by intensity. `legs` is guarded by its weekly volume
    instead, which is why it is not asked here.
    """
    last = {
        PATTERN_PULL: snapshot.last_heavy_pull,
        PATTERN_PUSH: snapshot.last_heavy_push,
    }.get(pattern)
    if last is None:
        return False
    return snapshot.as_of - last < timedelta(days=HEAVY_GAP_DAYS)


def suggest(
    snapshot: TrainingSnapshot,
    *,
    catalogue: Sequence[Exercise] = CATALOGUE,
) -> Suggestion:
    """
    What to train on `snapshot.as_of`, given everything that already happened.

    Takes the snapshot rather than a session: the same call answers the page and
    the skill, and neither can be «почти по канону». Returns the whole answer —
    offer, exclusions, gates, intensity and volume — because a caller that got
    only the list would have to re-derive the reasons and would derive them
    differently.
    """
    excluded: list[Excluded] = []
    gates: list[FiredGate] = []
    offered: list[str] = []
    fired: set[str] = set()

    for exercise in catalogue:
        complaint = _blocked_by_complaints(exercise, snapshot.open_complaints)
        if complaint is not None:
            reason = (
                f"открытая жалоба «{complaint}»: {exercise.name} нагружает эту "
                "область, вернётся после закрытия жалобы"
            )
            excluded.append(Excluded(exercise.name, GATE_COMPLAINT, reason))
            if GATE_COMPLAINT not in fired:
                fired.add(GATE_COMPLAINT)
                gates.append(FiredGate(GATE_COMPLAINT, reason))
            continue

        if _heavy_recently(snapshot, exercise.pattern):
            reason = (
                f"тяжёлый {exercise.pattern} был меньше {HEAVY_GAP_DAYS} дней "
                "назад: 48 часов между тяжёлыми повторами паттерна не прошли"
            )
            excluded.append(Excluded(exercise.name, GATE_HEAVY_48H, reason))
            if GATE_HEAVY_48H not in fired:
                fired.add(GATE_HEAVY_48H)
                gates.append(FiredGate(GATE_HEAVY_48H, reason))
            continue

        if snapshot.week_sets.get(exercise.pattern, 0) >= WEEK_SETS_LIMIT:
            reason = (
                f"{exercise.pattern} за неделю набрал "
                f"{snapshot.week_sets.get(exercise.pattern, 0)} подходов при "
                f"потолке {WEEK_SETS_LIMIT}: паттерн уступает место другому"
            )
            excluded.append(Excluded(exercise.name, GATE_WEEK_VOLUME, reason))
            if GATE_WEEK_VOLUME not in fired:
                fired.add(GATE_WEEK_VOLUME)
                gates.append(FiredGate(GATE_WEEK_VOLUME, reason))
            continue

        offered.append(exercise.name)

    rir = RIR_HARD
    volume = FULL_VOLUME_FACTOR

    if len(snapshot.near_failure_days) >= NEAR_FAILURE_WEEK_LIMIT:
        rir = RIR_SOFT
        gates.append(
            FiredGate(
                GATE_NEAR_FAILURE,
                f"near-failure дней за неделю: {len(snapshot.near_failure_days)} "
                f"при лимите {NEAR_FAILURE_WEEK_LIMIT} — остаток недели в "
                f"{RIR_SOFT}, без исключений",
            )
        )

    if snapshot.skipped_days >= SKIPPED_DAYS_LIMIT:
        rir = RIR_RETURN
        volume = RETURN_VOLUME_FACTOR
        gates.append(
            FiredGate(
                GATE_RETURN,
                f"пропусков подряд: {snapshot.skipped_days} — неделя не "
                f"догоняется, первый день возврата идёт в {RIR_RETURN} и на "
                f"{round((1 - RETURN_VOLUME_FACTOR) * 100)}% меньше объёма",
            )
        )

    return Suggestion(
        exercises=tuple(offered),
        excluded=tuple(excluded),
        gates=tuple(gates),
        rir=rir,
        volume_factor=volume,
    )
