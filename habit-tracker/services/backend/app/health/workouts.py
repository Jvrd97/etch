# [review:need-review] PHASE-02/70
# summary: the workout as the server keeps it — local date of the START (so a session across midnight is one day), the Russian label of an activity type the phone names in snake_case, and the bounds a wire value must meet
"""
Workouts (`HKWorkout`) are events, not hourly buckets.

A run has a type, an interval, a duration, energy, distance and a heart rate; adding
it into "minutes of exercise per day" would lose what is worth reading. The phone
sends each one under its HealthKit UUID and the server upserts on that UUID, so a
window re-read on every sync never doubles a workout.

**A workout belongs to the day it started.** A 23:30-00:30 run is one entry on its
start date, not two halves.
"""

from __future__ import annotations

from datetime import date, datetime

from app.health.aggregate import local_time

# The phone names a type in snake_case (`HKWorkoutActivityType` has no stable string
# of its own). The pattern is the whole contract: anything else is a bug on the phone.
ACTIVITY_TYPE_PATTERN = r"^[a-z][a-z0-9_]*$"
MAX_ACTIVITY_TYPE_LENGTH = 40

# Shown for a type the label table does not know: HealthKit adds activity types
# every year, and a new one must show up as a workout, not be refused.
UNKNOWN_ACTIVITY_LABEL = "Тренировка"

ACTIVITY_LABELS: dict[str, str] = {
    "running": "Бег",
    "walking": "Ходьба",
    "hiking": "Поход",
    "cycling": "Велосипед",
    "swimming": "Плавание",
    "rowing": "Гребля",
    "elliptical": "Эллипс",
    "stair_climbing": "Лестница",
    "traditional_strength_training": "Силовая тренировка",
    "functional_strength_training": "Функциональная тренировка",
    "core_training": "Тренировка кора",
    "high_intensity_interval_training": "Интервальная тренировка",
    "cross_training": "Кросс-тренинг",
    "yoga": "Йога",
    "pilates": "Пилатес",
    "dance": "Танцы",
    "cooldown": "Заминка",
    "flexibility": "Растяжка",
    "mixed_cardio": "Кардио",
    "jump_rope": "Скакалка",
    "kickboxing": "Кикбоксинг",
    "boxing": "Бокс",
    "martial_arts": "Единоборства",
    "tennis": "Теннис",
    "table_tennis": "Настольный теннис",
    "badminton": "Бадминтон",
    "squash": "Сквош",
    "soccer": "Футбол",
    "basketball": "Баскетбол",
    "volleyball": "Волейбол",
    "golf": "Гольф",
    "skating_sports": "Коньки",
    "downhill_skiing": "Горные лыжи",
    "cross_country_skiing": "Беговые лыжи",
    "snowboarding": "Сноуборд",
    "climbing": "Скалолазание",
    "paddle_sports": "Гребля на байдарке",
    "surfing_sports": "Сёрфинг",
    "wheelchair_walk_pace": "Коляска, шаг",
    "wheelchair_run_pace": "Коляска, бег",
    "other": "Другая тренировка",
}


def activity_label(activity_type: str) -> str:
    """The Russian name of an activity type, or the generic one for an unknown type."""
    return ACTIVITY_LABELS.get(activity_type, UNKNOWN_ACTIVITY_LABEL)


def local_date_of_start(started_at: datetime, utc_offset_minutes: int) -> date:
    """The date on the device's own clock when the workout began."""
    return local_time(started_at, utc_offset_minutes).date()
