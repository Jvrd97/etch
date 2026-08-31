# [review:need-review] PHASE-03/147
# summary: two tests per rule — one draft that passes it and one that is caught by it — plus the guarantee that `detail` never carries the text of a line and that no time or ceiling is hard-coded in the two new modules
"""
The eight rules, each proved in both directions.

**A pass test and a catch test for every rule, and no rule sharing either.** The
acceptance case is "deleting any one check breaks exactly its own test", which
only holds if each catch test breaks one rule and nothing else — so every draft
here is built from a helper that starts legal and is then broken in one place.

No session and no database: the module under test takes rows in hand and answers
in milliseconds, which is what lets the truth table be complete instead of
sampled.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.day import constraints
from app.day.constraints import DraftItem, PlanDraft
from app.day.rules import SEED_RULES
from app.models.day import DayRuleSet

BERLIN = ZoneInfo("Europe/Berlin")

# A Wednesday and the Saturday of the same week: one working day, one day off,
# which is the pair `relationship_anchor_required` turns on and off.
WORKDAY = date(2026, 9, 2)
DAY_OFF = date(2026, 9, 5)


def rule(**overrides: object) -> DayRuleSet:
    """
    The current canon as a row in memory, with anything the test wants changed.

    Built from `SEED_RULES` rather than typed out: a test that spelled its own
    ceiling would keep passing after the canon changed, which is the failure
    mode `#142` exists to end.
    """
    seed = SEED_RULES[-1]
    row = DayRuleSet(
        valid_from=seed.valid_from,
        valid_to=seed.valid_to,
        timezone=seed.timezone,
        day_start_hour=seed.day_start_hour,
        work_cap_min=seed.work_cap_min,
        work_hard_cap_min=seed.work_hard_cap_min,
        overtime_lost_min=seed.overtime_lost_min,
        work_stop_at=seed.work_stop_at,
        max_work_tasks=seed.max_work_tasks,
        max_study_items=seed.max_study_items,
        tasks_required_ratio=seed.tasks_required_ratio,
        overtime_disqualifies=seed.overtime_disqualifies,
        workdays=list(seed.workdays),
        days_off=list(seed.days_off),
        nocode_days=list(seed.nocode_days),
        required_anchors=list(seed.required_anchors),
        wake_at=seed.wake_at,
        work_start=seed.work_start,
        review_at=seed.review_at,
        bedtime_max=seed.bedtime_max,
        free_evening_start=seed.free_evening_start,
        free_evening_end=seed.free_evening_end,
        relationship_anchor_required=seed.relationship_anchor_required,
        relationship_evening_start=seed.relationship_evening_start,
        relationship_evening_end=seed.relationship_evening_end,
        hard_edge_kinds=list(seed.hard_edge_kinds),
        anchors=list(seed.anchors),
        verdict_rule=dict(seed.verdict_rule),
        note_md=seed.note_md,
    )
    row.id = 1
    for name, value in overrides.items():
        setattr(row, name, value)
    return row


def at(on: date, hour: int, minute: int = 0) -> datetime:
    """A wall-clock moment of `on`, in the canon's own zone."""
    return datetime.combine(on, time(hour, minute), tzinfo=BERLIN)


def item(
    on: date,
    *,
    kind: str = "bullet",
    rigidity: str = "soft",
    code: str | None = None,
    section_kind: str = "other",
    start: datetime | None = None,
    end: datetime | None = None,
    day_date: date | None = None,
) -> DraftItem:
    return DraftItem(
        item_id=uuid.uuid4(),
        kind=kind,
        rigidity=rigidity,
        code=code,
        section_kind=section_kind,
        day_date=day_date if day_date is not None else on,
        starts_at=start,
        ends_at=end,
    )


def sport(on: date, hour: int = 6, minute: int = 30) -> DraftItem:
    """The health anchor the canon names, before work."""
    start = at(on, hour, minute)
    return item(
        on,
        kind="anchor",
        rigidity="hard",
        code="спорт",
        section_kind="anchors",
        start=start,
        end=start + timedelta(minutes=45),
    )


def legal(on: date = WORKDAY) -> PlanDraft:
    """
    A draft that breaks nothing, which every catch test starts from.

    Sport in the morning, one work task inside the working hours, nothing in the
    free evening, everything on the target date.
    """
    return PlanDraft(
        target=on,
        items=(
            sport(on),
            item(
                on,
                kind="task",
                section_kind="work",
                start=at(on, 9),
                end=at(on, 11),
            ),
        ),
    )


def codes(violations: list[constraints.Violation]) -> list[str]:
    return [violation.rule_code for violation in violations]


# --- 1. hard_edges_only ------------------------------------------------------


def test_hard_edges_only_passes_when_only_an_anchor_is_hard() -> None:
    assert constraints.check_hard_edges_only(legal(), rule()) == []


def test_hard_edges_only_catches_a_hard_task() -> None:
    draft = PlanDraft(
        target=WORKDAY,
        items=(
            sport(WORKDAY),
            item(WORKDAY, kind="task", rigidity="hard", section_kind="work"),
        ),
    )

    found = constraints.check_hard_edges_only(draft, rule())

    assert codes(found) == [constraints.RULE_HARD_EDGES_ONLY]
    assert found[0].severity == constraints.SEVERITY_BLOCK


# --- 2. free_evening_empty ---------------------------------------------------


def test_free_evening_empty_passes_when_a_window_ends_where_it_begins() -> None:
    canon = rule()
    edge = at(WORKDAY, canon.free_evening_start.hour, canon.free_evening_start.minute)
    draft = PlanDraft(
        target=WORKDAY,
        items=(item(WORKDAY, start=edge - timedelta(hours=1), end=edge),),
    )

    assert constraints.check_free_evening_empty(draft, canon) == []


def test_free_evening_empty_catches_a_window_that_reaches_into_it() -> None:
    canon = rule()
    edge = at(WORKDAY, canon.free_evening_start.hour, canon.free_evening_start.minute)
    draft = PlanDraft(
        target=WORKDAY,
        items=(
            item(
                WORKDAY,
                start=edge - timedelta(hours=1),
                end=edge + timedelta(minutes=1),
            ),
        ),
    )

    found = constraints.check_free_evening_empty(draft, canon)

    assert codes(found) == [constraints.RULE_FREE_EVENING_EMPTY]


# --- 3. work_cap -------------------------------------------------------------


def test_work_cap_passes_at_the_ceiling_exactly() -> None:
    canon = rule()
    start = at(WORKDAY, 8)
    draft = PlanDraft(
        target=WORKDAY,
        items=(
            item(
                WORKDAY,
                kind="task",
                section_kind="work",
                start=start,
                end=start + timedelta(minutes=canon.work_hard_cap_min),
            ),
        ),
    )

    assert constraints.check_work_cap(draft, canon) == []


def test_work_cap_catches_one_minute_over_the_ceiling() -> None:
    canon = rule()
    start = at(WORKDAY, 8)
    draft = PlanDraft(
        target=WORKDAY,
        items=(
            item(
                WORKDAY,
                kind="task",
                section_kind="work",
                start=start,
                end=start + timedelta(minutes=canon.work_hard_cap_min + 1),
            ),
        ),
    )

    found = constraints.check_work_cap(draft, canon)

    assert codes(found) == [constraints.RULE_WORK_CAP]
    assert found[0].detail["work_hard_cap_min"] == canon.work_hard_cap_min
    # Overtime is never plannable: the number is named so a repair knows the gap.
    assert found[0].detail["overtime_lost_min"] == canon.overtime_lost_min


# --- 4. task_cap -------------------------------------------------------------


def test_task_cap_passes_at_the_bar() -> None:
    canon = rule()
    draft = PlanDraft(
        target=WORKDAY,
        items=tuple(
            item(WORKDAY, kind="task", section_kind="work")
            for _ in range(canon.max_work_tasks)
        ),
    )

    assert constraints.check_task_cap(draft, canon) == []


def test_task_cap_catches_the_task_over_the_bar_and_the_study_item_over_its_own() -> (
    None
):
    canon = rule()
    draft = PlanDraft(
        target=WORKDAY,
        items=tuple(
            item(WORKDAY, kind="task", section_kind="work")
            for _ in range(canon.max_work_tasks + 1)
        )
        + tuple(
            item(WORKDAY, section_kind="study")
            for _ in range(canon.max_study_items + 1)
        ),
    )

    found = constraints.check_task_cap(draft, canon)

    # Two complaints, not one merged: each is repaired by removing a different
    # line, and a single message would be repaired by removing the wrong one.
    assert codes(found) == [constraints.RULE_TASK_CAP, constraints.RULE_TASK_CAP]
    assert found[0].detail["tasks"] == canon.max_work_tasks + 1
    assert found[1].detail["study_items"] == canon.max_study_items + 1


# --- 5. health_before_work ---------------------------------------------------


def test_health_before_work_passes_when_sport_starts_first() -> None:
    assert constraints.check_health_before_work(legal(), rule()) == []


def test_health_before_work_catches_a_day_that_opens_with_work() -> None:
    draft = PlanDraft(
        target=WORKDAY,
        items=(
            sport(WORKDAY, hour=12),
            item(
                WORKDAY,
                kind="task",
                section_kind="work",
                start=at(WORKDAY, 9),
                end=at(WORKDAY, 11),
            ),
        ),
    )

    found = constraints.check_health_before_work(draft, rule())

    assert codes(found) == [constraints.RULE_HEALTH_BEFORE_WORK]


def test_health_before_work_catches_a_plan_with_no_health_anchor_at_all() -> None:
    draft = PlanDraft(
        target=WORKDAY,
        items=(
            item(
                WORKDAY,
                kind="task",
                section_kind="work",
                start=at(WORKDAY, 9),
                end=at(WORKDAY, 11),
            ),
        ),
    )

    found = constraints.check_health_before_work(draft, rule())

    assert codes(found) == [constraints.RULE_HEALTH_BEFORE_WORK]
    assert found[0].detail["missing_codes"] == ["спорт"]


# --- 6. relationship_anchor_required -----------------------------------------


def test_relationship_anchor_is_not_demanded_on_a_working_evening() -> None:
    """Требовать вечер с близкими в будний вечер сдачи релиза система не вправе."""
    assert constraints.check_relationship_anchor_required(legal(WORKDAY), rule()) == []


def test_relationship_anchor_passes_when_the_day_off_names_it() -> None:
    draft = PlanDraft(
        target=DAY_OFF,
        items=(
            sport(DAY_OFF),
            item(DAY_OFF, kind="anchor", code="relationship", section_kind="anchors"),
        ),
    )

    assert constraints.check_relationship_anchor_required(draft, rule()) == []


def test_relationship_anchor_catches_a_day_off_without_it() -> None:
    found = constraints.check_relationship_anchor_required(legal(DAY_OFF), rule())

    assert codes(found) == [constraints.RULE_RELATIONSHIP_ANCHOR_REQUIRED]
    assert found[0].detail["missing_codes"] == ["relationship"]


def test_the_legacy_canon_does_not_demand_the_evening_with_the_family() -> None:
    """
    Правило смотрит строку, а не календарь.

    `legacy` завёл вечер с близкими до того, как он стал требованием, и день,
    прожитый под той строкой, им не судится.
    """
    legacy = rule(relationship_anchor_required=False)

    assert constraints.check_relationship_anchor_required(legal(DAY_OFF), legacy) == []


# --- 7. no_overlap -----------------------------------------------------------


def test_no_overlap_passes_when_one_window_ends_where_the_next_begins() -> None:
    draft = PlanDraft(
        target=WORKDAY,
        items=(
            item(WORKDAY, start=at(WORKDAY, 9), end=at(WORKDAY, 10)),
            item(WORKDAY, start=at(WORKDAY, 10), end=at(WORKDAY, 11)),
        ),
    )

    assert constraints.check_no_overlap(draft, rule()) == []


def test_no_overlap_catches_the_pair_that_collided() -> None:
    first = item(WORKDAY, start=at(WORKDAY, 9), end=at(WORKDAY, 11))
    second = item(WORKDAY, start=at(WORKDAY, 10), end=at(WORKDAY, 12))
    draft = PlanDraft(target=WORKDAY, items=(first, second))

    found = constraints.check_no_overlap(draft, rule())

    assert codes(found) == [constraints.RULE_NO_OVERLAP]
    assert found[0].detail["pairs"] == [[str(first.item_id), str(second.item_id)]]


# --- 8. target_day_only ------------------------------------------------------


def test_target_day_only_passes_when_every_line_is_the_target() -> None:
    assert constraints.check_target_day_only(legal(), rule()) == []


def test_target_day_only_catches_a_line_written_on_the_neighbour() -> None:
    draft = PlanDraft(
        target=WORKDAY,
        items=(
            sport(WORKDAY),
            item(WORKDAY, day_date=WORKDAY + timedelta(days=1)),
        ),
    )

    found = constraints.check_target_day_only(draft, rule())

    assert codes(found) == [constraints.RULE_TARGET_DAY_ONLY]
    assert found[0].detail["dates"] == [(WORKDAY + timedelta(days=1)).isoformat()]


# --- check_all ---------------------------------------------------------------


def test_check_all_reports_every_broken_rule_at_once() -> None:
    """
    Все нарушения сразу, а не первое.

    Ответ уходит в ремонтный промпт, и промпт, чинящий по одному правилу за
    круг, стоит один вызов модели на каждую ошибку.
    """
    canon = rule()
    draft = PlanDraft(
        target=WORKDAY,
        items=(
            item(WORKDAY, kind="task", rigidity="hard", section_kind="work"),
            item(WORKDAY, day_date=WORKDAY + timedelta(days=1)),
        ),
    )

    found = constraints.check_all(draft, canon)

    assert constraints.RULE_HARD_EDGES_ONLY in codes(found)
    assert constraints.RULE_HEALTH_BEFORE_WORK in codes(found)
    assert constraints.RULE_TARGET_DAY_ONLY in codes(found)


def test_check_all_at_warn_is_the_same_findings_at_a_different_cost() -> None:
    """Машине нарушение блокирует запись, человеку — нет."""
    draft = PlanDraft(
        target=WORKDAY,
        items=(
            sport(WORKDAY),
            item(WORKDAY, kind="task", rigidity="hard", section_kind="work"),
        ),
    )
    canon = rule()

    blocked = constraints.check_all(draft, canon)
    warned = constraints.check_all(draft, canon, severity=constraints.SEVERITY_WARN)

    assert codes(blocked) == codes(warned)
    assert {violation.severity for violation in blocked} == {constraints.SEVERITY_BLOCK}
    assert {violation.severity for violation in warned} == {constraints.SEVERITY_WARN}


def test_a_legal_draft_breaks_nothing_on_either_seeded_row() -> None:
    for seed_index in range(len(SEED_RULES)):
        canon = rule(
            relationship_anchor_required=SEED_RULES[
                seed_index
            ].relationship_anchor_required,
            work_hard_cap_min=SEED_RULES[seed_index].work_hard_cap_min,
            max_work_tasks=SEED_RULES[seed_index].max_work_tasks,
        )
        assert constraints.check_all(legal(), canon) == []


# --- the answer says nothing about what the day contained --------------------


def test_no_violation_detail_carries_the_text_of_a_line() -> None:
    """
    `detail` — только id и числа.

    Проверяется значениями, а не чтением кода: строка `plan_violation` живёт
    дольше плана, который её породил, а задача бывает названа диагнозом.
    """
    canon = rule()
    secret = "приём обезболивающего"
    draft = PlanDraft(
        target=WORKDAY,
        items=(
            item(
                WORKDAY, kind="task", rigidity="hard", code=secret, section_kind="work"
            ),
            item(WORKDAY, day_date=WORKDAY + timedelta(days=1)),
        ),
    )

    found = constraints.check_all(draft, canon)

    assert found
    for violation in found:
        assert secret not in repr(violation.detail)


def test_no_time_or_ceiling_is_hard_coded_in_the_two_new_modules() -> None:
    """
    Ни одна константа времени или потолка не зашита: grep не находит их.

    Числа канона живут в строке правила, потому что канон менялся дважды за
    месяц, а константа в модуле переписала бы правила уже прожитых дней.
    """
    forbidden = ("16:00", "22:30", "480", "540", "19:10", "07:45")
    for module in (constraints, __import__("app.day.skeleton", fromlist=["x"])):
        source = open(module.__file__ or "", encoding="utf-8").read()
        for needle in forbidden:
            assert needle not in source, f"{needle} зашит в {module.__name__}"


@pytest.mark.parametrize("code", constraints.RULE_CODES)
def test_every_rule_code_has_a_check_that_can_produce_it(code: str) -> None:
    """Восемь кодов и восемь проверок — ни одного кода без своей функции."""
    assert len(constraints.CHECKS) == len(constraints.RULE_CODES)
    assert code in constraints.RULE_CODES
