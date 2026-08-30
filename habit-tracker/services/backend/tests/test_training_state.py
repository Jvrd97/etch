# [review:need-review] PHASE-03/92
# summary: the pure recompute of training state — two skipped days in a row raise skipped_days to 2, a gap in the dates does not, the week counter starts on Monday, heavy is told apart from touched, and two recomputes in a row give the identical snapshot
"""Пересчёт `training_state` из строк `training_day` — без базы и без часов."""

from datetime import date

from app.training.state import ComplaintFact, TrainingDayFact, recompute, week_start

# Понедельник и вся неделя вокруг него — даты выбраны так, чтобы «с
# понедельника» было видно глазами, а не выводилось из календаря в голове.
MONDAY = date(2026, 8, 24)
FRIDAY = date(2026, 8, 28)
SATURDAY = date(2026, 8, 29)
SUNDAY = date(2026, 8, 30)


def test_week_starts_on_monday() -> None:
    assert week_start(SUNDAY) == MONDAY
    assert week_start(MONDAY) == MONDAY


def test_two_skipped_days_in_a_row_raise_the_counter() -> None:
    # Приёмка тикета: 29 и 30 августа подряд без тренировки — `skipped_days`
    # обязан стать двойкой, потому что на ней стоит гейт возврата.
    state = recompute(
        [
            TrainingDayFact(FRIDAY, patterns=("push",), sets={"push": 3}),
            TrainingDayFact(SATURDAY, skipped=True),
            TrainingDayFact(SUNDAY, skipped=True),
        ],
        [],
        SUNDAY,
    )

    assert state.skipped_days == 2


def test_a_gap_between_skipped_days_is_not_a_streak() -> None:
    # Два пропуска с рабочим днём между ними — две отдельные осечки, а не серия:
    # иначе неделя возврата уезжала бы в минус тридцать процентов ни за что.
    state = recompute(
        [
            TrainingDayFact(FRIDAY, skipped=True),
            TrainingDayFact(SATURDAY, patterns=("pull",)),
            TrainingDayFact(SUNDAY, skipped=True),
        ],
        [],
        SUNDAY,
    )

    assert state.skipped_days == 1


def test_heavy_is_not_the_same_as_touched() -> None:
    # «Один подход подтягиваний, сколько идёт» — это pull-день, который не
    # должен закрывать завтрашний pull-день сорока восемью часами.
    state = recompute(
        [
            TrainingDayFact(FRIDAY, patterns=("pull",), heavy_patterns=("pull",)),
            TrainingDayFact(SUNDAY, patterns=("pull",)),
        ],
        [],
        SUNDAY,
    )

    assert state.last_heavy_pull == FRIDAY


def test_week_sets_count_from_monday_only() -> None:
    last_week = MONDAY.replace(day=21)
    state = recompute(
        [
            TrainingDayFact(last_week, patterns=("pull",), sets={"pull": 9}),
            TrainingDayFact(FRIDAY, patterns=("pull",), sets={"pull": 4}),
            TrainingDayFact(SATURDAY, patterns=("push",), sets={"push": 8}),
        ],
        [],
        SUNDAY,
    )

    assert state.week_sets == {"pull": 4, "push": 8}


def test_near_failure_days_are_this_week_only() -> None:
    state = recompute(
        [
            TrainingDayFact(MONDAY.replace(day=17), near_failure=True),
            TrainingDayFact(FRIDAY, near_failure=True),
            TrainingDayFact(SATURDAY, near_failure=True),
        ],
        [],
        SUNDAY,
    )

    assert state.near_failure_days == (FRIDAY, SATURDAY)


def test_only_open_complaints_reach_the_state() -> None:
    state = recompute(
        [],
        [
            ComplaintFact("левое плечо", date(2026, 8, 10), "open"),
            ComplaintFact("колено", date(2026, 8, 12), "closed"),
        ],
        SUNDAY,
    )

    assert state.open_complaints == ("левое плечо",)


def test_recompute_twice_gives_the_same_snapshot() -> None:
    # Приёмка тикета: пересчёт идемпотентен. Снимок — значение функции от строк,
    # поэтому равенство здесь и есть «обновился только recomputed_at»: сама
    # отметка времени живёт в строке, а не в снимке.
    days = [
        TrainingDayFact(
            FRIDAY,
            patterns=("push", "core"),
            heavy_patterns=("push",),
            sets={"push": 3, "core": 2},
            outdoor_done=True,
        ),
        TrainingDayFact(SATURDAY, skipped=True),
    ]
    complaints = [ComplaintFact("левое плечо", date(2026, 8, 10), "open")]

    first = recompute(days, complaints, SUNDAY)
    second = recompute(days, complaints, SUNDAY)

    assert first == second


def test_outdoor_is_read_off_its_own_flag() -> None:
    state = recompute(
        [
            TrainingDayFact(FRIDAY, outdoor_done=True),
            TrainingDayFact(SATURDAY, outdoor_done=False),
        ],
        [],
        SUNDAY,
    )

    assert state.last_outdoor == FRIDAY
