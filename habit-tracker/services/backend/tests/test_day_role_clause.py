"""
Клауз роли: рабочий день без акта CTO или архитектора не выигран.

Здесь проверяется ровно то, ради чего клауз заведён. Что день из восьмисот
восьмидесяти тимлидских минут с одним архитектурным актом выигран, а тот же день
без акта — проигран: доля времени в дневной вердикт не входит, входит факт акта.
Что выходной и no-code день клаузом не судятся вовсе — не «проходят его», а не
имеют его в списке. Что день, прожитый легаси-правилом, остаётся с тем вердиктом,
что был: в те дни ролей не измеряли. Что новая строка канона с выключенным
клаузом не переписывает вчерашний день. И что вердикт выведен из списка клаузов —
пути, на котором клаузы говорят одно, а вердикт другое, нет.
"""

# [review:need-review] PHASE-03/137
# summary: tests for the role clause — a workday won by one architect act and lost without it, the clause absent on a day off and on a no-code day, the legacy canon keeping its verdicts, a new rule row with the clause off leaving yesterday alone, the human-readable detail naming the role and the act, and the verdict derived from the clause list with no path to disagree with it
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import day as day_crud
from app.crud import role as role_crud
from app.crud import summary as summary_crud
from app.day.evaluate import (
    REASON_ANCHORS,
    REASON_NONE,
    REASON_OVERTIME,
    REASON_ROLE_ACT,
    REASON_TASKS,
    VERDICT_LOST,
    VERDICT_WON,
    DayFacts,
    RoleActFact,
    evaluate_day,
    role_clause_applies,
)
from app.day.marks import TaskCounts
from app.day.rules import KIND_OFF, KIND_WORK, SEED_RULES, RuleSeed
from app.models.day import DayRuleSet
from app.models.role import ROLE_CODE_ARCHITECT, ROLE_CODE_CTO, ROLE_CODE_TECHLEAD
from tests.conftest import record_role_act

DAY_URL = "/api/v1/day"

# Понедельник — рабочий день обоих канонов.
WORK_DAY = date(2026, 8, 24)
# Суббота той же недели: выходной по расписанию канона.
DAY_OFF = date(2026, 8, 29)
# Вторник — no-code день по расписанию канона.
NOCODE_DAY = date(2026, 8, 25)
# День, прожитый легаси-правилом: канон сменился 2026-08-17.
LEGACY_DAY = date(2026, 8, 10)

# Восемь часов ровно: под потолком действующего канона, то есть день не может
# быть проигран переработкой и разница между двумя случаями — только акт.
EIGHT_HOURS_MIN = 480

LEGACY_SEED, CURRENT_SEED = SEED_RULES


def rule(seed: RuleSeed, rule_id: int) -> DayRuleSet:
    """Строка канона как значение, без сессии."""
    return DayRuleSet(
        id=rule_id,
        valid_from=seed.valid_from,
        valid_to=seed.valid_to,
        timezone=seed.timezone,
        day_start_hour=seed.day_start_hour,
        work_cap_min=seed.work_cap_min,
        work_hard_cap_min=seed.work_hard_cap_min,
        work_stop_at=seed.work_stop_at,
        max_work_tasks=seed.max_work_tasks,
        tasks_required_ratio=seed.tasks_required_ratio,
        overtime_disqualifies=seed.overtime_disqualifies,
        workdays=list(seed.workdays),
        nocode_days=list(seed.nocode_days),
        required_anchors=list(seed.required_anchors),
        role_clause_enabled=seed.role_clause_enabled,
        role_clause_roles=seed.role_clause_roles,
        note_md=seed.note_md,
    )


CURRENT = rule(CURRENT_SEED, 2)
LEGACY = rule(LEGACY_SEED, 1)

ARCHITECT_ACT = RoleActFact(
    role_code=ROLE_CODE_ARCHITECT,
    role_title="Архитектор",
    act_kind="adr_written",
    title="ADR-0020",
)
TECHLEAD_ACT = RoleActFact(
    role_code=ROLE_CODE_TECHLEAD,
    role_title="Техлид",
    act_kind="review_done",
    title="ревью двадцати пулл-реквестов",
)

ROLE_TITLES = {
    ROLE_CODE_CTO: "CTO",
    ROLE_CODE_ARCHITECT: "Архитектор",
    ROLE_CODE_TECHLEAD: "Техлид",
}


def counts(done: int, planned: int) -> TaskCounts:
    return TaskCounts(
        planned=planned, done=done, failed=0, skipped=0, pending=planned - done
    )


def facts(
    *,
    role_acts: tuple[RoleActFact, ...] = (),
    day_kind: str | None = KIND_WORK,
    is_nocode: bool = False,
    work_minutes: int | None = EIGHT_HOURS_MIN,
    tasks: TaskCounts | None = None,
    anchors: TaskCounts | None = None,
) -> DayFacts:
    """День, который выигран всем, кроме того, что сломает вызывающий."""
    return DayFacts(
        closed=True,
        tasks=tasks if tasks is not None else counts(4, 4),
        anchors=anchors if anchors is not None else counts(5, 5),
        work_minutes=work_minutes,
        day_kind=day_kind,
        is_nocode=is_nocode,
        role_acts=role_acts,
        role_titles=dict(ROLE_TITLES),
    )


def clause_of(verdict: Any, code: str) -> Any:
    """Один клауз вердикта по коду, либо None — его в списке нет."""
    return next((one for one in verdict.clauses if one.code == code), None)


def _assert_clauses_without_role(clauses: list[dict[str, Any]]) -> None:
    """
    День, который клауз роли не судит: три условия канона есть, роли нет.

    Требует именно три кода, а не «`role_act` отсутствует»: второе истинно и на
    пустом списке, то есть зелено и тогда, когда клаузы до ответа не доехали
    вовсе.
    """
    assert [one["code"] for one in clauses] == [
        REASON_OVERTIME,
        REASON_ANCHORS,
        REASON_TASKS,
    ]
    assert all(one["passed"] for one in clauses)
    assert all(one["detail"] for one in clauses)


class TestTheClauseItself:
    """Восемь часов тимлида плюс один акт архитектора — и без него."""

    def test_a_workday_with_one_architect_act_passes_the_clause(self) -> None:
        verdict = evaluate_day(CURRENT, facts(role_acts=(ARCHITECT_ACT,)))

        clause = clause_of(verdict, REASON_ROLE_ACT)
        assert clause is not None
        assert clause.passed is True
        assert verdict.verdict == VERDICT_WON
        assert verdict.reason == REASON_NONE

    def test_the_same_day_without_an_act_is_lost(self) -> None:
        """Приёмка: тот же день без акта — проигранный, и назван клауз роли."""
        verdict = evaluate_day(CURRENT, facts())

        clause = clause_of(verdict, REASON_ROLE_ACT)
        assert clause is not None
        assert clause.passed is False
        assert verdict.verdict == VERDICT_LOST
        assert verdict.reason == REASON_ROLE_ACT

    def test_eight_hours_of_tech_lead_do_not_close_the_clause(self) -> None:
        """
        Доля времени клауз не закрывает: считается акт, а не минуты.

        День из восьми часов ревью стопроцентно тимлидский по минутам. Акт
        тимлида — не акт роли, отличной от тимлида, и день без второго не выигран
        независимо от того, сколько минут в первом.
        """
        verdict = evaluate_day(CURRENT, facts(role_acts=(TECHLEAD_ACT,)))

        assert verdict.verdict == VERDICT_LOST
        assert verdict.reason == REASON_ROLE_ACT

    def test_the_clause_line_names_the_role_and_the_act(self) -> None:
        """Приёмка: строка называет роль и акт, а не «условие не выполнено»."""
        passed = clause_of(
            evaluate_day(CURRENT, facts(role_acts=(ARCHITECT_ACT,))), REASON_ROLE_ACT
        )
        failed = clause_of(evaluate_day(CURRENT, facts()), REASON_ROLE_ACT)

        assert passed is not None and failed is not None
        assert "Архитектор" in passed.detail
        assert "ADR-0020" in passed.detail
        assert "CTO" in failed.detail
        assert "Архитектор" in failed.detail
        assert "role_act" not in failed.detail


class TestWhenTheClauseDoesNotApply:
    """Выходной, no-code и легаси-правило клаузом не судятся."""

    def test_a_day_off_has_no_role_clause_at_all(self) -> None:
        """Приёмка: клауз не показан и на вердикт не влияет."""
        verdict = evaluate_day(CURRENT, facts(day_kind=KIND_OFF))

        assert clause_of(verdict, REASON_ROLE_ACT) is None
        assert verdict.verdict == VERDICT_WON

    def test_a_nocode_day_has_no_role_clause_at_all(self) -> None:
        verdict = evaluate_day(CURRENT, facts(is_nocode=True))

        assert clause_of(verdict, REASON_ROLE_ACT) is None
        assert verdict.verdict == VERDICT_WON

    def test_a_day_judged_by_the_legacy_rule_keeps_its_verdict(self) -> None:
        """
        Приёмка: день легаси-правила остаётся тем же, чем был до этого тикета.

        В момент действия легаси-правила ролей не измеряли — таблиц `role_act` не
        существовало, — и требовать акт задним числом значило бы снимать день за
        то, чего в тот день нельзя было ни сделать, ни записать.
        """
        verdict = evaluate_day(LEGACY, facts())

        assert clause_of(verdict, REASON_ROLE_ACT) is None
        assert verdict.verdict == VERDICT_WON

    def test_a_day_with_no_row_of_its_own_is_not_judged_by_the_clause(self) -> None:
        """Импортированная история без строки `day`: вид дня неизвестен."""
        assert role_clause_applies(CURRENT, facts(day_kind=None)) is False

    def test_a_new_rule_row_with_the_clause_off_changes_nothing(self) -> None:
        """Приёмка: строка с выключенным клаузом не меняет вердикт вчерашнего дня."""
        without = rule(CURRENT_SEED, 3)
        without.role_clause_enabled = False

        assert evaluate_day(without, facts()).verdict == VERDICT_WON
        assert clause_of(evaluate_day(without, facts()), REASON_ROLE_ACT) is None


class TestVerdictFollowsTheClauses:
    """Вердикт выведен из списка клаузов, а не сосчитан рядом с ним."""

    def test_no_case_lets_the_clauses_and_the_verdict_disagree(self) -> None:
        """
        Вся таблица истинности разом: вердикт всегда равен «все клаузы прошли».

        Проверяется перебором, а не глазами: до `#137` функция возвращалась на
        первом непройденном условии, и «что ещё было не так» досчитывалось по
        счётчикам вручную — там и жила возможность разойтись.
        """
        space = [
            facts(role_acts=acts, work_minutes=minutes, tasks=tasks, anchors=anchors)
            for acts in ((), (ARCHITECT_ACT,))
            for minutes in (400, 700)
            for tasks in (counts(4, 4), counts(2, 4))
            for anchors in (counts(5, 5), counts(3, 5))
        ]
        for one in space:
            verdict = evaluate_day(CURRENT, one)
            passed = all(clause.passed for clause in verdict.clauses)
            assert verdict.verdict == (VERDICT_WON if passed else VERDICT_LOST)
            if not passed:
                first = next(c for c in verdict.clauses if not c.passed)
                assert verdict.reason == first.code

    def test_the_role_clause_is_weighed_last(self) -> None:
        """
        День, сорванный и переработкой, и ролью, назван переработкой.

        Порядок не украшение: переработка и сорванные якоря объясняют, почему
        акта не случилось, и отправлять человека чинить акт значило бы указать
        не на ту поломку.
        """
        overtime = evaluate_day(CURRENT, facts(work_minutes=700))
        anchors = evaluate_day(CURRENT, facts(anchors=counts(3, 5)))
        tasks = evaluate_day(CURRENT, facts(tasks=counts(2, 4)))

        assert overtime.reason == REASON_OVERTIME
        assert anchors.reason == REASON_ANCHORS
        assert tasks.reason == REASON_TASKS

    def test_every_clause_carries_words_a_person_can_act_on(self) -> None:
        """Пустая расшифровка — клауз, который читается кодом и ничем больше."""
        verdict = evaluate_day(CURRENT, facts(role_acts=(ARCHITECT_ACT,)))

        assert len(verdict.clauses) == 4
        assert all(clause.detail for clause in verdict.clauses)


@pytest.mark.asyncio
class TestOverTheWire:
    """Клауз доезжает до ответа дня рядом с якорями, задачами и переработкой."""

    async def test_the_day_response_carries_the_clause_list(
        self, client: AsyncClient, db_session: AsyncSession, seeded_goal: int
    ) -> None:
        await day_crud.seed_rules(db_session)
        await record_role_act(db_session, WORK_DAY)
        await db_session.commit()

        response = await client.get(f"{DAY_URL}/{WORK_DAY.isoformat()}")

        assert response.status_code == 200, response.text
        clauses = response.json()["summary"]["clauses"]
        codes = [one["code"] for one in clauses]
        assert REASON_ROLE_ACT in codes
        role = next(one for one in clauses if one["code"] == REASON_ROLE_ACT)
        assert role["passed"] is True
        assert "ADR-0020" in role["detail"]

    async def test_a_workday_without_an_act_is_closed_as_lost(
        self, client: AsyncClient, db_session: AsyncSession, seeded_goal: int
    ) -> None:
        """
        Приёмка целиком: тот же день без акта закрывается проигранным.

        И объясняет, чем именно: `verdict_reason` — код первого непройденного
        клауза, и разбор, из которого он выведен, ответ несёт рядом. Без него
        экран говорит «проигран / role_act» и молчит о том, что не сошлось.
        """
        await day_crud.seed_rules(db_session)
        await role_crud.seed_roles(db_session)
        await db_session.commit()

        closed = await client.post(
            f"{DAY_URL}/{WORK_DAY.isoformat()}/close",
            json={"work_minutes": EIGHT_HOURS_MIN, "body_md": "ровный день"},
        )

        assert closed.status_code == 200, closed.text
        body = closed.json()
        assert body["verdict"] == VERDICT_LOST
        assert body["verdict_reason"] == REASON_ROLE_ACT

        clauses = body["clauses"]
        assert [one["code"] for one in clauses] == [
            REASON_OVERTIME,
            REASON_ANCHORS,
            REASON_TASKS,
            REASON_ROLE_ACT,
        ]
        assert [one["code"] for one in clauses if not one["passed"]] == [
            REASON_ROLE_ACT
        ]
        assert all(one["detail"] for one in clauses)

    async def test_the_same_day_with_an_act_is_closed_as_won(
        self, client: AsyncClient, db_session: AsyncSession, seeded_goal: int
    ) -> None:
        await day_crud.seed_rules(db_session)
        await record_role_act(db_session, WORK_DAY)
        await db_session.commit()

        closed = await client.post(
            f"{DAY_URL}/{WORK_DAY.isoformat()}/close",
            json={"work_minutes": EIGHT_HOURS_MIN, "body_md": "ровный день"},
        )

        assert closed.status_code == 200, closed.text
        assert closed.json()["verdict"] == VERDICT_WON

    async def test_a_day_off_closes_without_the_clause(
        self, client: AsyncClient, db_session: AsyncSession, seeded_goal: int
    ) -> None:
        """
        Приёмка: выходной закрывается без клауза — его нет в списке.

        «Нет в списке» проверяется списком, который есть: три условия канона
        закрытый день несёт всегда, и отсутствие роли среди них — факт, а не
        следствие пустоты. Проверка «`role_act` не в пустом списке» истинна
        сама по себе и три дня держала дефект `_to_response` зелёным.
        """
        await day_crud.seed_rules(db_session)
        await role_crud.seed_roles(db_session)
        await db_session.commit()

        closed = await client.post(
            f"{DAY_URL}/{DAY_OFF.isoformat()}/close", json={"body_md": "выходной"}
        )

        assert closed.status_code == 200, closed.text
        assert closed.json()["verdict"] == VERDICT_WON
        _assert_clauses_without_role(closed.json()["clauses"])

    async def test_a_nocode_day_closes_without_the_clause(
        self, client: AsyncClient, db_session: AsyncSession, seeded_goal: int
    ) -> None:
        await day_crud.seed_rules(db_session)
        await role_crud.seed_roles(db_session)
        await db_session.commit()

        closed = await client.post(
            f"{DAY_URL}/{NOCODE_DAY.isoformat()}/close",
            json={"work_minutes": EIGHT_HOURS_MIN, "body_md": "учебный день"},
        )

        assert closed.status_code == 200, closed.text
        assert closed.json()["verdict"] == VERDICT_WON
        _assert_clauses_without_role(closed.json()["clauses"])


@pytest.mark.asyncio
class TestVersionedCanon:
    """Клауз — поле строки правила, поэтому его смена это новая строка."""

    async def test_the_seeded_canon_enables_the_clause_only_on_the_current_row(
        self, db_session: AsyncSession
    ) -> None:
        await day_crud.seed_rules(db_session)
        await db_session.flush()

        rules = await day_crud.list_rules(db_session)
        by_open = {one.valid_to is None: one for one in rules}

        assert by_open[True].role_clause_enabled is True
        assert by_open[False].role_clause_enabled is False

    async def test_a_published_row_can_switch_the_clause_off(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """
        Клауз снимается новой версией канона, а не правкой действующей.

        Ровно тот же приём, что у потолка часов: вчерашний день оценён правилом
        своего времени, и снятие клауза не переписывает ни одного вердикта.
        """
        await day_crud.seed_rules(db_session)
        await db_session.commit()
        history = (await client.get("/api/v1/day-rule-sets")).json()
        current = (await client.get("/api/v1/day-rule-sets/current")).json()
        starts_on = date.fromisoformat(history["earliest_valid_from"]) + timedelta(
            days=30
        )

        published = await client.post(
            "/api/v1/day-rule-sets",
            json={
                "valid_from": starts_on.isoformat(),
                "timezone": current["timezone"],
                "day_start_hour": current["day_start_hour"],
                "work_cap_min": current["work_cap_min"],
                "work_hard_cap_min": current["work_hard_cap_min"],
                "work_stop_at": current["work_stop_at"],
                "max_work_tasks": current["max_work_tasks"],
                "tasks_required_ratio": str(Decimal("1.00")),
                "overtime_disqualifies": current["overtime_disqualifies"],
                "workdays": current["workdays"],
                "nocode_days": current["nocode_days"],
                "required_anchors": current["required_anchors"],
                "role_clause_enabled": False,
                "note_md": "клауз роли снят: акты выродились в ритуал",
            },
        )

        assert published.status_code == 201, published.text
        assert published.json()["role_clause_enabled"] is False

    async def test_a_clause_switched_on_without_roles_is_refused(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Клауз без ролей объявил бы проигранным каждый рабочий день."""
        await day_crud.seed_rules(db_session)
        await db_session.commit()
        history = (await client.get("/api/v1/day-rule-sets")).json()
        current = (await client.get("/api/v1/day-rule-sets/current")).json()
        starts_on = date.fromisoformat(history["earliest_valid_from"]) + timedelta(
            days=30
        )

        refused = await client.post(
            "/api/v1/day-rule-sets",
            json={
                "valid_from": starts_on.isoformat(),
                "timezone": current["timezone"],
                "day_start_hour": current["day_start_hour"],
                "work_cap_min": current["work_cap_min"],
                "work_hard_cap_min": current["work_hard_cap_min"],
                "work_stop_at": current["work_stop_at"],
                "max_work_tasks": current["max_work_tasks"],
                "tasks_required_ratio": str(Decimal("1.00")),
                "overtime_disqualifies": current["overtime_disqualifies"],
                "workdays": current["workdays"],
                "nocode_days": current["nocode_days"],
                "required_anchors": current["required_anchors"],
                "role_clause_roles": "  ,  ",
                "note_md": "клауз без ролей",
            },
        )

        assert refused.status_code == 422, refused.text


@pytest.mark.asyncio
class TestRecompute:
    """Пересчёт истории не переписывает дни, прожитые без клауза."""

    async def test_recompute_leaves_a_legacy_day_alone(
        self, client: AsyncClient, db_session: AsyncSession, seeded_goal: int
    ) -> None:
        await day_crud.seed_rules(db_session)
        await role_crud.seed_roles(db_session)
        await db_session.commit()

        closed = await client.post(
            f"{DAY_URL}/{LEGACY_DAY.isoformat()}/close",
            json={"work_minutes": EIGHT_HOURS_MIN, "body_md": "августовский день"},
        )
        assert closed.status_code == 200, closed.text
        before = closed.json()["verdict"]

        await summary_crud.recompute_history(db_session)
        await db_session.flush()

        after = await summary_crud.get_summary(db_session, LEGACY_DAY)
        assert after is not None
        assert after.verdict == before == VERDICT_WON
