# [review:need-review] PHASE-03/245, PHASE-03/239, PHASE-03/255
# summary: tests of the one health-metric comparison the week review and the advice share, and of the one Russian rendering of its numbers for the prompts
"""
Метрика здоровья «против прошлого окна» и её слова.

Обзор недели и совет считали одно и то же в двух копиях; тест держит одну и
проверяет её без базы: среднее — по дням с данными, а день без данных — не ноль.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.health import HEALTH_SPECS, compare_windows, metric_days
from app.llm.health_format import (
    average_basis,
    comparison_text,
    health_value,
    plural_form,
    signed_health_delta,
)

START = date(2026, 10, 12)


def days(first: date, count: int) -> list[date]:
    return [first + timedelta(days=i) for i in range(count)]


class TestCompareWindows:
    def test_average_is_over_days_with_data_not_over_all_days(self) -> None:
        current = days(START + timedelta(days=7), 7)
        earlier = days(START, 7)
        by_day = {current[0]: 30.0, current[1]: 60.0}

        result = compare_windows(by_day, current, earlier)

        # Два дня из семи: 45 минут в день, а не 90 / 7.
        assert (result.days_with_data, result.total, result.avg_per_day) == (
            2,
            90.0,
            45.0,
        )

    def test_a_day_without_data_is_not_a_zero_in_the_previous_window(self) -> None:
        current = days(START + timedelta(days=7), 3)
        earlier = days(START, 3)
        by_day = {current[0]: 8000.0, earlier[0]: 4000.0, earlier[1]: 6000.0}

        result = compare_windows(by_day, current, earlier)

        assert result.previous_days_with_data == 2
        assert result.previous_avg_per_day == 5000.0
        assert result.delta_avg_per_day == 3000.0

    def test_no_data_in_either_window_is_none_not_zero(self) -> None:
        current = days(START + timedelta(days=7), 3)

        result = compare_windows({}, current, days(START, 3))

        assert (result.total, result.avg_per_day, result.delta_avg_per_day) == (
            None,
            None,
            None,
        )
        assert result.days_with_data == 0

    def test_no_delta_when_only_one_window_has_data(self) -> None:
        current = days(START + timedelta(days=7), 3)

        result = compare_windows({current[0]: 10.0}, current, days(START, 3))

        assert result.avg_per_day == 10.0
        assert result.previous_avg_per_day is None
        assert result.delta_avg_per_day is None

    def test_the_average_is_rounded_to_one_digit(self) -> None:
        current = days(START + timedelta(days=7), 3)
        by_day = {current[0]: 1.0, current[1]: 1.0, current[2]: 2.0}

        assert compare_windows(by_day, current, []).avg_per_day == 1.3

    def test_days_outside_the_windows_are_ignored(self) -> None:
        current = days(START + timedelta(days=7), 2)
        stray = {START + timedelta(days=30): 999.0, current[0]: 5.0}

        assert compare_windows(stray, current, []).total == 5.0


def test_the_catalogue_of_specs_has_one_row_per_key() -> None:
    keys = [spec.key for spec in HEALTH_SPECS]

    assert len(keys) == len(set(keys))
    assert {"sleep", "steps", "workouts", "resting_hr"} <= set(keys)


async def test_an_unknown_metric_key_is_an_error_not_a_silent_gap(
    db_session: AsyncSession,
) -> None:
    """A typo in `keys` must not turn into a metric that quietly never appears."""
    with pytest.raises(ValueError, match="stepz"):
        await metric_days(db_session, ("steps", "stepz"), START, START)


async def test_known_keys_come_back_in_the_order_of_the_specs(
    db_session: AsyncSession,
) -> None:
    items = await metric_days(db_session, ("workouts", "steps"), START, START)

    assert [item.spec.key for item in items] == ["steps", "workouts"]


class TestPluralForm:
    @pytest.mark.parametrize(
        ("count", "word"),
        [
            (1, "шаг"),
            (2, "шага"),
            (4, "шага"),
            (5, "шагов"),
            (11, "шагов"),
            (12, "шагов"),
            (14, "шагов"),
            (21, "шаг"),
            (22, "шага"),
            (25, "шагов"),
            (100, "шагов"),
            (101, "шаг"),
            (111, "шагов"),
            (7421, "шаг"),
        ],
    )
    def test_whole_numbers(self, count: int, word: str) -> None:
        assert plural_form(count, "шаг", "шага", "шагов") == word

    def test_a_fraction_takes_the_genitive_singular(self) -> None:
        assert plural_form(1.5, "шаг", "шага", "шагов") == "шага"
        assert plural_form(7421.5, "шаг", "шага", "шагов") == "шага"

    @pytest.mark.parametrize(
        ("count", "word"),
        [
            (112, "шагов"),
            (113, "шагов"),
            (114, "шагов"),
            (111, "шагов"),
            (100_000, "шагов"),
            (100_001, "шаг"),
            (100_002, "шага"),
            (100_011, "шагов"),
            (100_112, "шагов"),
            (1_000_001, "шаг"),
            (1_234_567, "шагов"),
            (2_000_003, "шага"),
        ],
    )
    def test_the_hundreds_and_the_big_numbers(self, count: int, word: str) -> None:
        assert plural_form(count, "шаг", "шага", "шагов") == word

    def test_the_form_follows_the_printed_number_not_the_raw_one(self) -> None:
        """111.9999999 is printed as «112», and «112» takes «шагов», not «шага»."""
        assert plural_form(111.9999999, "шаг", "шага", "шагов") == "шагов"
        assert plural_form(100_000.0000001, "шаг", "шага", "шагов") == "шагов"


class TestHealthValue:
    def test_steps_decline_by_the_number(self) -> None:
        assert health_value("steps", "count", 1) == "1 шаг"
        assert health_value("steps", "count", 2) == "2 шага"
        assert health_value("steps", "count", 5) == "5 шагов"
        assert health_value("steps", "count", 8000) == "8000 шагов"
        assert health_value("steps", "count", 8001) == "8001 шаг"
        assert health_value("steps", "count", 12) == "12 шагов"

    def test_a_fractional_average_of_steps_is_genitive_singular(self) -> None:
        assert health_value("steps", "count", 7421.5) == "7421.5 шага"

    @pytest.mark.parametrize(
        ("value", "text"),
        [
            (112, "112 шагов"),
            (113, "113 шагов"),
            (114, "114 шагов"),
            (100_000, "100000 шагов"),
            (100_001, "100001 шаг"),
            (123_456, "123456 шагов"),
            (1_000_000, "1000000 шагов"),
            (12_345_678, "12345678 шагов"),
            (111.9999999, "112 шагов"),
            (100_000.0000001, "100000 шагов"),
        ],
    )
    def test_the_unit_is_declined_by_the_printed_number(
        self, value: float, text: str
    ) -> None:
        assert health_value("steps", "count", value) == text

    def test_a_big_number_is_never_printed_with_an_exponent(self) -> None:
        assert "e" not in health_value("steps", "count", 12_345_678.0)
        assert "e" not in health_value("other", "kcal", 1e15)

    def test_minutes_are_hours_and_minutes(self) -> None:
        assert health_value("workouts", "min", 30) == "0 ч 30 мин"
        assert health_value("sleep", "min", 430) == "7 ч 10 мин"

    def test_resting_heart_rate_is_an_invariable_unit(self) -> None:
        assert health_value("resting_hr", "count/min", 60) == "60 уд/мин"
        assert health_value("resting_hr", "count/min", 1) == "1 уд/мин"

    def test_an_unknown_metric_keeps_the_catalogue_unit(self) -> None:
        assert health_value("other", "kcal", 12.5) == "12.5 kcal"
        assert health_value("other", None, 3) == "3"


class TestSignedHealthDelta:
    def test_the_sign_is_printed_and_the_unit_declined_by_the_size(self) -> None:
        assert signed_health_delta("steps", "count", 1000) == "+1000 шагов"
        assert signed_health_delta("steps", "count", -1) == "-1 шаг"
        assert signed_health_delta("resting_hr", "count/min", -4) == "-4 уд/мин"

    def test_zero_has_no_sign(self) -> None:
        assert signed_health_delta("steps", "count", 0) == "0 шагов"

    def test_a_delta_that_prints_as_zero_has_no_sign(self) -> None:
        assert signed_health_delta("steps", "count", -0.0000001) == "0 шагов"
        assert signed_health_delta("steps", "count", 0.0000001) == "0 шагов"
        assert signed_health_delta("workouts", "min", -0.3) == "0 ч 0 мин"

    def test_no_delta_is_said_in_words(self) -> None:
        assert signed_health_delta("steps", "count", None) == "нет данных для сравнения"


def test_the_average_names_its_denominator_without_a_second_average() -> None:
    assert average_basis(2, 7) == "по дням с данными: 2 из 7 дн."


class TestComparisonText:
    def test_the_change_names_the_days_of_the_other_window(self) -> None:
        text = comparison_text("steps", "count", 1000, 5, 7, "к прошлому окну")
        assert text == "+1000 шагов к прошлому окну, против 5 из 7 дн."

    def test_no_delta_has_nothing_to_name(self) -> None:
        text = comparison_text("steps", "count", None, 0, 7, "к прошлому окну")
        assert text == "нет данных для сравнения"
