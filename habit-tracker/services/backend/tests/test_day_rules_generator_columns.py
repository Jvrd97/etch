# [review:need-review] PHASE-03/142
# summary: the map of the day and the verdict formula as data — `day_map` reads the edges, the free evening and the ceilings off the rule row, `evaluate_day` takes the composition of anchors and the order of the reasons from it, a new row moves only later days, `hard_edge_kinds` comes from the row rather than from a constant, and a date no rule covers answers 404
"""
The canon of the day read as data, not as prose.

Two claims of `#142` are what these tests hold down.

**Карту дня видно числами из строки правила.** `day_map` is the single reading
of the row, `GET /day/{date}` carries it, and every number on the screen comes
from a column — so a change of canon is visible without redeploying anything.

**Новая строка правила меняет только последующие дни.** Composition of anchors
is a column, so adding «вечер с близкими» to the canon loses the days lived
after it and leaves yesterday exactly as it was judged. That is the whole reason
the table is versioned, and it is the one property a constant in a module could
never have.
"""

from collections.abc import AsyncGenerator
from datetime import date, time
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import day as day_crud
from app.day.evaluate import (
    DEFAULT_REASON_ORDER,
    MISSING_ANCHOR_KINDS,
    REASON_ANCHORS,
    REASON_NONE,
    REASON_TASKS,
    VERDICT_LOST,
    VERDICT_WON,
    DayFacts,
    UnknownVerdictReason,
    evaluate_day,
    verdict_reasons,
)
from app.day.marks import TaskCounts
from app.day.plan_validate import ItemFacts, PlanRejected, check_hard_rigidity
from app.day.rules import (
    EDGE_BEDTIME,
    EDGE_REVIEW,
    EDGE_SPORT,
    EDGE_WAKE,
    EDGE_WORK_START,
    SEED_RULES,
    day_map,
)
from app.models.day import DayRuleSet
from app.models.mark import MARK_DONE

DAY_URL = "/api/v1/day"

LEGACY_SEED, CURRENT_SEED = SEED_RULES

# The day the two rules of the test meet: a plan lived on `BEFORE` under a canon
# of five anchors, and the canon of six starts the next morning.
BEFORE = date(2026, 9, 10)
AFTER = date(2026, 9, 11)

WAKE = "подъём"
RELATIONSHIP = "relationship"


@pytest.fixture(autouse=True)
async def seeded_rules(
    db_session: AsyncSession, seeded_goal: int
) -> AsyncGenerator[None, None]:
    """
    The rule table as a migrated database has it; `create_all` has no seed.

    `seeded_goal` comes with it: the task of the plan below names goal 1 of the
    quarter, and since `#93` that column has a foreign key.
    """
    await day_crud.seed_rules(db_session)
    yield


def make_rule(
    rule_id: int = 1,
    *,
    anchors: tuple[str, ...] = (WAKE,),
    verdict_rule: dict[str, Any] | None = None,
    hard_edge_kinds: tuple[str, ...] = ("anchor", "hard_point"),
) -> DayRuleSet:
    """A rule row built in memory, complete enough for the map and the verdict."""
    return DayRuleSet(
        id=rule_id,
        valid_from=date(2026, 8, 17),
        valid_to=None,
        timezone="Europe/Berlin",
        day_start_hour=4,
        work_cap_min=480,
        work_hard_cap_min=540,
        overtime_lost_min=600,
        work_stop_at=time(16, 0),
        max_work_tasks=4,
        max_study_items=2,
        tasks_required_ratio=Decimal("1.00"),
        overtime_disqualifies=True,
        workdays=[1, 2, 3, 4, 5],
        days_off=[6, 7],
        nocode_days=[2, 4],
        required_anchors=[WAKE],
        wake_at=time(6, 0),
        work_start=time(7, 45),
        review_at=time(15, 40),
        bedtime_max=time(22, 30),
        free_evening_start=time(19, 10),
        free_evening_end=time(21, 0),
        relationship_anchor_required=True,
        relationship_evening_start=time(18, 30),
        relationship_evening_end=time(21, 0),
        hard_edge_kinds=list(hard_edge_kinds),
        anchors=list(anchors),
        verdict_rule=verdict_rule if verdict_rule is not None else {},
        note_md="",
    )


def counts(done: int, planned: int) -> TaskCounts:
    return TaskCounts(
        planned=planned, done=done, failed=0, skipped=0, pending=planned - done
    )


def facts(
    *,
    anchor_kinds: frozenset[str] | None,
    tasks: TaskCounts | None = None,
    anchors: TaskCounts | None = None,
) -> DayFacts:
    """A closed day that was won on the counters, unless the caller breaks it."""
    return DayFacts(
        closed=True,
        tasks=tasks if tasks is not None else counts(1, 1),
        anchors=anchors if anchors is not None else counts(1, 1),
        work_minutes=400,
        anchor_kinds=anchor_kinds,
    )


# --- the map of the day is numbers of the row --------------------------------


def test_the_map_reads_the_edges_off_the_row() -> None:
    """
    The acceptance case: подъём, старт работы, ревью и отбой — числа строки.

    Before `#142` these four lived only in `config.md`, so the plan of a day
    could not be compared with the map of the day at all.
    """
    canon = day_map(make_rule())

    at = {edge.kind: edge.at for edge in canon.edges}
    assert at[EDGE_WAKE] == time(6, 0)
    assert at[EDGE_WORK_START] == time(7, 45)
    assert at[EDGE_REVIEW] == time(15, 40)
    assert at[EDGE_BEDTIME] == time(22, 30)


def test_the_edge_the_canon_does_not_clock_says_so() -> None:
    """Спорт стоит до работы, но часа у него в каноне нет — и это null."""
    canon = day_map(make_rule())

    sport = next(edge for edge in canon.edges if edge.kind == EDGE_SPORT)
    assert sport.at is None
    assert sport.label == "спорт"


def test_the_free_evening_is_an_interval_of_the_row() -> None:
    canon = day_map(make_rule())

    assert (canon.free_evening.start, canon.free_evening.end) == (
        time(19, 10),
        time(21, 0),
    )
    assert canon.overtime_lost_min == 600
    assert canon.max_study_items == 2


def test_the_evening_with_the_family_is_a_flag_of_the_row() -> None:
    """
    Снятие флага новой строкой убирает требование, не трогая кода.

    Проверку планированием делает `#147`; здесь держится то, ради чего она
    вообще возможна: требование — поле, а не ветка в планировщике.
    """
    required = day_map(make_rule())
    rule = make_rule()
    rule.relationship_anchor_required = False
    lifted = day_map(rule)

    assert required.relationship_anchor_required is True
    assert lifted.relationship_anchor_required is False
    assert lifted.relationship_evening.start == time(18, 30)


# --- the composition of anchors decides the verdict ---------------------------


def test_a_day_that_closed_every_anchor_of_its_canon_is_won() -> None:
    verdict = evaluate_day(
        make_rule(anchors=(WAKE,)), facts(anchor_kinds=frozenset({WAKE}))
    )

    assert (verdict.verdict, verdict.reason) == (VERDICT_WON, REASON_NONE)
    assert verdict.missing_anchor_kinds == ()


def test_an_anchor_the_canon_names_and_the_day_missed_loses_it() -> None:
    """«Вечер с близкими» весит в вердикте наравне с якорями здоровья."""
    rule = make_rule(anchors=(WAKE, RELATIONSHIP))

    verdict = evaluate_day(rule, facts(anchor_kinds=frozenset({WAKE})))

    assert (verdict.verdict, verdict.reason) == (VERDICT_LOST, REASON_ANCHORS)
    assert verdict.missing_anchor_kinds == (RELATIONSHIP,)


def test_a_new_composition_does_not_move_the_verdict_of_an_older_day() -> None:
    """
    The acceptance case, in its purest form: the same day, the two rules.

    Один и тот же прожитый день, судимый строкой, под которой он прожит, и
    строкой, которая пришла позже. Первый ответ не меняется — иначе смена канона
    задним числом переписывала бы историю, ради чего таблица и версионируется.
    """
    lived = facts(anchor_kinds=frozenset({WAKE}))

    under_the_old_canon = evaluate_day(make_rule(1, anchors=(WAKE,)), lived)
    under_the_new_canon = evaluate_day(
        make_rule(2, anchors=(WAKE, RELATIONSHIP)), lived
    )

    assert under_the_old_canon.verdict == VERDICT_WON
    assert under_the_new_canon.verdict == VERDICT_LOST


def test_an_unmeasured_composition_falls_back_to_the_counter_and_says_so() -> None:
    """
    «Состав не измерен» — не «ни одного якоря»: план, не назвавший якоря кодами,
    судится своим счётчиком, а пропуск называется вслух — тем же способом, что и
    неизмеренные минуты работы.
    """
    verdict = evaluate_day(
        make_rule(anchors=(WAKE, RELATIONSHIP)), facts(anchor_kinds=None)
    )

    assert verdict.verdict == VERDICT_WON
    assert MISSING_ANCHOR_KINDS in verdict.missing_data
    assert verdict.missing_anchor_kinds == ()


# --- the formula of the verdict is a row too ---------------------------------


def test_a_row_without_a_formula_is_judged_by_the_canon_order() -> None:
    assert verdict_reasons(make_rule()) == DEFAULT_REASON_ORDER


def test_dropping_a_condition_from_the_row_stops_it_lowering_the_day() -> None:
    """Требование к якорям снимается строкой, а не правкой `evaluate_day`."""
    lived = facts(anchor_kinds=frozenset(), anchors=counts(0, 1))

    strict = evaluate_day(make_rule(anchors=(WAKE,)), lived)
    lenient = evaluate_day(
        make_rule(
            anchors=(WAKE,), verdict_rule={"reason_order": ["overtime", "tasks"]}
        ),
        lived,
    )

    assert (strict.verdict, strict.reason) == (VERDICT_LOST, REASON_ANCHORS)
    assert lenient.verdict == VERDICT_WON


def test_the_order_of_the_row_decides_which_condition_is_named() -> None:
    """Порядок — приоритет `config.md`; он тоже данные, а не расположение веток."""
    broken = facts(anchor_kinds=frozenset(), anchors=counts(0, 1), tasks=counts(0, 1))

    health_first = evaluate_day(make_rule(anchors=(WAKE,)), broken)
    tasks_first = evaluate_day(
        make_rule(
            anchors=(WAKE,),
            verdict_rule={"reason_order": ["tasks", "anchors", "overtime"]},
        ),
        broken,
    )

    assert health_first.reason == REASON_ANCHORS
    assert tasks_first.reason == REASON_TASKS


def test_a_condition_nobody_can_weigh_is_refused_loudly() -> None:
    """Опечатка в формуле не проглатывается: иначе день считался бы не по ней."""
    rule = make_rule(verdict_rule={"reason_order": ["overtim"]})

    with pytest.raises(UnknownVerdictReason) as error:
        verdict_reasons(rule)

    assert "overtim" in str(error.value)


# --- hardness is a list of the row -------------------------------------------


def test_the_kinds_allowed_to_be_hard_come_from_the_row() -> None:
    """
    Решение 2026-08-30: жёсткость разрешена всему `hard_point`. Список — колонка,
    поэтому канон, который его сузит, ничего в коде не правит.
    """
    meeting = ItemFacts(
        kind="hard_point",
        rigidity="hard",
        code="C1",
        text_plain="созвон в 11:00",
        has_window=True,
    )

    check_hard_rigidity([meeting], make_rule())

    with pytest.raises(PlanRejected) as error:
        check_hard_rigidity([meeting], make_rule(hard_edge_kinds=("anchor",)))
    assert error.value.error == "hard_is_not_an_edge"


# --- the seed of both rows ----------------------------------------------------


def test_the_current_row_carries_the_evening_with_the_family_and_legacy_does_not() -> (
    None
):
    """Третий приоритет стал каноном вместе с `#142`, а не задним числом."""
    assert RELATIONSHIP in CURRENT_SEED.anchors
    assert RELATIONSHIP not in LEGACY_SEED.anchors
    assert CURRENT_SEED.relationship_anchor_required is True
    assert LEGACY_SEED.relationship_anchor_required is False


def test_the_seed_carries_the_map_of_config_md() -> None:
    assert CURRENT_SEED.wake_at == time(6, 0)
    assert CURRENT_SEED.work_start == time(7, 45)
    assert CURRENT_SEED.review_at == time(15, 40)
    assert CURRENT_SEED.bedtime_max == time(22, 30)
    assert CURRENT_SEED.overtime_lost_min == 600
    assert LEGACY_SEED.overtime_lost_min == 600


# --- the same map over HTTP ---------------------------------------------------


async def test_the_day_screen_gets_the_map_as_numbers(client: AsyncClient) -> None:
    """
    The acceptance case: карта дня приезжает числами строки правила.

    Не вёрсткой: страница рисует то, что прислали, и новый канон меняет её без
    единой правки фронта.
    """
    response = await client.get(f"{DAY_URL}/{BEFORE.isoformat()}")

    assert response.status_code == 200, response.text
    canon = response.json()["day_map"]
    at = {edge["kind"]: edge["at"] for edge in canon["edges"]}
    assert at[EDGE_WAKE] == "06:00:00"
    assert at[EDGE_REVIEW] == "15:40:00"
    assert at[EDGE_BEDTIME] == "22:30:00"
    assert at[EDGE_SPORT] is None
    assert canon["free_evening"] == {"start": "19:10:00", "end": "21:00:00"}
    assert canon["relationship_anchor_required"] is True
    assert RELATIONSHIP in canon["anchors"]
    assert canon["verdict_reasons"] == list(DEFAULT_REASON_ORDER)
    assert canon["rule_set_id"] == response.json()["rule"]["id"]


async def test_a_date_no_rule_covers_answers_with_an_error_not_a_default(
    client: AsyncClient,
) -> None:
    """
    День, который не покрывает ни один период правил, — ошибка, а не молчаливое
    умолчание: вердикт по выдуманному канону никто никогда не проживал.
    """
    response = await client.get(f"{DAY_URL}/2019-12-31")

    assert response.status_code == 404
    assert "day_rule_set" in response.json()["detail"]


# --- a new row over HTTP moves only the days after it -------------------------


async def _plan_with_a_named_anchor(client: AsyncClient, on: date) -> None:
    """One task and one anchor the plan names by code, both closed."""
    response = await client.post(
        f"{DAY_URL}/{on.isoformat()}/plan",
        json={
            "sections": [
                {
                    "kind": "work",
                    "title": "День",
                    "items": [
                        {
                            "kind": "task",
                            "code": "W1",
                            "text_md": "Задача W1",
                            "window": "09:00-10:00",
                            "done_criterion": "письмо отправлено",
                            "quarter_goal_id": 1,
                        },
                        {"kind": "anchor", "code": WAKE, "text_md": "Подъём 06:00"},
                    ],
                }
            ]
        },
    )
    assert response.status_code == 201, response.text
    for item in response.json()["sections"][0]["items"]:
        marked = await client.put(
            f"{DAY_URL}/{on.isoformat()}/marks/{item['id']}",
            json={"state": MARK_DONE},
        )
        assert marked.status_code == 200, marked.text


async def _split_the_canon(db_session: AsyncSession) -> None:
    """
    Two rules that meet on `AFTER`: пять якорей до, шесть — после.

    Действующая строка сида укорачивается, а не переписывается: смена канона —
    это новая строка, и обе остаются в таблице ровно затем, чтобы прожитый день
    сохранил ту, под которой прожит.
    """
    rules = await day_crud.list_rules(db_session)
    current = max(rules, key=lambda rule: rule.valid_from)
    current.valid_to = AFTER
    current.anchors = [WAKE]
    current.relationship_anchor_required = False
    db_session.add(
        DayRuleSet(
            valid_from=AFTER,
            valid_to=None,
            timezone=current.timezone,
            day_start_hour=current.day_start_hour,
            work_cap_min=current.work_cap_min,
            work_hard_cap_min=current.work_hard_cap_min,
            overtime_lost_min=current.overtime_lost_min,
            work_stop_at=current.work_stop_at,
            max_work_tasks=current.max_work_tasks,
            max_study_items=current.max_study_items,
            tasks_required_ratio=current.tasks_required_ratio,
            overtime_disqualifies=current.overtime_disqualifies,
            workdays=list(current.workdays),
            days_off=list(current.days_off),
            nocode_days=list(current.nocode_days),
            required_anchors=list(current.required_anchors),
            wake_at=current.wake_at,
            work_start=current.work_start,
            review_at=current.review_at,
            bedtime_max=current.bedtime_max,
            free_evening_start=current.free_evening_start,
            free_evening_end=current.free_evening_end,
            relationship_anchor_required=True,
            relationship_evening_start=current.relationship_evening_start,
            relationship_evening_end=current.relationship_evening_end,
            hard_edge_kinds=list(current.hard_edge_kinds),
            anchors=[WAKE, RELATIONSHIP],
            verdict_rule=dict(current.verdict_rule),
            note_md="канон с вечером с близкими",
        )
    )
    await db_session.flush()


async def test_a_new_row_of_anchors_leaves_yesterdays_verdict_where_it_was(
    client: AsyncClient, db_session: AsyncSession, seeded_goal: int
) -> None:
    """
    The acceptance case over HTTP, including the recompute.

    Закрытие любого дня пересчитывает всю историю (`recompute_history`), так что
    именно здесь смена канона могла бы задним числом переписать вердикт. Она не
    переписывает: день судится строкой, которую покрывает его дата.
    """
    await _split_the_canon(db_session)
    await _plan_with_a_named_anchor(client, BEFORE)
    closed = await client.post(
        f"{DAY_URL}/{BEFORE.isoformat()}/close", json={"work_minutes": 400}
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["verdict"] == VERDICT_WON

    # A day of the new canon, lived exactly the same way, loses on the anchor
    # the new row added — and closing it re-judges every day recorded.
    await _plan_with_a_named_anchor(client, AFTER)
    later = await client.post(
        f"{DAY_URL}/{AFTER.isoformat()}/close", json={"work_minutes": 400}
    )
    assert later.status_code == 200, later.text
    assert (later.json()["verdict"], later.json()["verdict_reason"]) == (
        VERDICT_LOST,
        REASON_ANCHORS,
    )

    yesterday = await client.get(f"{DAY_URL}/{BEFORE.isoformat()}")
    assert yesterday.json()["summary"]["verdict"] == VERDICT_WON
