# [review:need-review] PHASE-03/92
# summary: the gates of `/train` — an open shoulder complaint takes pull-ups out of the offer and closing it puts them back, a heavy pattern trained yesterday is not offered today, sixteen sets close a pattern, two near-failure days soften the week and two skipped days cut the volume of the return
"""Гейты подбора: что убирается из предложения и по какой причине."""

from datetime import date

from app.training.gates import (
    GATE_COMPLAINT,
    GATE_HEAVY_48H,
    GATE_NEAR_FAILURE,
    GATE_RETURN,
    GATE_WEEK_VOLUME,
    RETURN_VOLUME_FACTOR,
    RIR_HARD,
    RIR_RETURN,
    RIR_SOFT,
    WEEK_SETS_LIMIT,
    suggest,
)
from app.training.state import TrainingSnapshot, week_start

TODAY = date(2026, 8, 30)
YESTERDAY = date(2026, 8, 29)
PULLUPS = "подтягивания"
AUSTRALIAN = "австралийские тяги"


def snapshot(**patch: object) -> TrainingSnapshot:
    """A body with nothing wrong with it, patched one fact at a time."""
    base: dict[str, object] = {
        "as_of": TODAY,
        "week_starts_on": week_start(TODAY),
    }
    base.update(patch)
    return TrainingSnapshot(**base)  # type: ignore[arg-type]


def fired(codes: object) -> set[str]:
    """Gate codes of a suggestion, as a set for order-free comparison."""
    return {gate.code for gate in codes}  # type: ignore[attr-defined]


def test_open_shoulder_complaint_removes_pullups() -> None:
    # Приёмка тикета: жалоба «левое плечо» убирает подтягивания. Совпадение по
    # области, а не по названию упражнения — «левое плечо» содержит «плечо».
    offer = suggest(snapshot(open_complaints=("левое плечо",)))

    assert PULLUPS not in offer.exercises
    assert GATE_COMPLAINT in fired(offer.gates)
    assert any(one.exercise == PULLUPS for one in offer.excluded)


def test_horizontal_pull_survives_a_shoulder_complaint() -> None:
    # Канон снимает вертикальную тягу и жимы над головой, а не тягу вообще:
    # горизонтальная тяга в безболезненной амплитуде остаётся.
    offer = suggest(snapshot(open_complaints=("левое плечо",)))

    assert AUSTRALIAN in offer.exercises


def test_closing_the_complaint_brings_pullups_back() -> None:
    # Вторая половина той же приёмки: закрытие жалобы — это снимок без области,
    # и предложение возвращается само, без второго правила.
    offer = suggest(snapshot(open_complaints=()))

    assert PULLUPS in offer.exercises
    assert offer.excluded == ()


def test_heavy_pattern_trained_yesterday_is_not_offered_today() -> None:
    # Приёмка тикета: сорок восемь часов между тяжёлыми повторами паттерна.
    offer = suggest(snapshot(last_heavy_pull=YESTERDAY))

    assert PULLUPS not in offer.exercises
    assert AUSTRALIAN not in offer.exercises
    assert GATE_HEAVY_48H in fired(offer.gates)


def test_heavy_pattern_two_days_ago_is_offered_again() -> None:
    offer = suggest(snapshot(last_heavy_pull=date(2026, 8, 28)))

    assert PULLUPS in offer.exercises
    assert GATE_HEAVY_48H not in fired(offer.gates)


def test_a_pattern_at_the_weekly_ceiling_gives_way() -> None:
    offer = suggest(snapshot(week_sets={"push": WEEK_SETS_LIMIT}))

    assert "отжимания" not in offer.exercises
    assert GATE_WEEK_VOLUME in fired(offer.gates)
    assert PULLUPS in offer.exercises


def test_two_near_failure_days_soften_the_rest_of_the_week() -> None:
    offer = suggest(snapshot(near_failure_days=(date(2026, 8, 24), date(2026, 8, 25))))

    assert offer.rir == RIR_SOFT
    assert GATE_NEAR_FAILURE in fired(offer.gates)


def test_two_skipped_days_cut_the_volume_of_the_return() -> None:
    offer = suggest(snapshot(skipped_days=2))

    assert offer.rir == RIR_RETURN
    assert offer.volume_factor == RETURN_VOLUME_FACTOR
    assert GATE_RETURN in fired(offer.gates)


def test_a_clean_body_gets_the_whole_catalogue_at_full_intensity() -> None:
    offer = suggest(snapshot())

    assert offer.rir == RIR_HARD
    assert offer.volume_factor == 1.0
    assert offer.gates == ()
    assert PULLUPS in offer.exercises


def test_every_exclusion_carries_the_gate_that_made_it() -> None:
    # Список без объяснения — ровно тот ответ, из-за которого предложение
    # читается как «нелогично»; проверяем, что причина есть у каждой строки.
    offer = suggest(snapshot(open_complaints=("плечо",), last_heavy_pull=YESTERDAY))

    assert offer.excluded
    for one in offer.excluded:
        assert one.gate
        assert one.reason
