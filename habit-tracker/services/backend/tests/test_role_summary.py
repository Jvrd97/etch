"""
Недельная сводка по ролям: доли, отклонения, акты и сигнал «правила отстали».

Здесь проверяется место, где минуты наконец работают. Что доли считаются от
суммы рабочих минут и `unassigned` входит в знаменатель, а не выносится из него.
Что неделя без единой записи открывается пустой сводкой, а не нулями, выданными
за измерение. Что порог тридцати процентов срабатывает ровно на границе — по
отношению, а не по округлённому проценту, иначе 30,4% молча не поднимали бы
флаг. Что `format=md` несёт те же числа, что и `format=json`, до знака. И что
неделя из сорока часов, где на акты архитектора пришлось сорок минут, показывает
этот перекос числом.
"""

# [review:need-review] PHASE-03/138
# summary: tests for the period summary — shares over the sum of working minutes with `unassigned` in the denominator, an empty period answering with an empty summary rather than zeros, the 30% lag flag decided on the ratio at the exact boundary, the markdown block carrying the same numbers as the JSON, acts counted by kind, and one endpoint answering for a week and for a month alike
from datetime import date, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import role as role_crud
from app.roles.report import NO_ACTS_LINE, NO_DATA_LINE, TARGET_NOTE, render_summary_md
from app.models.role import (
    ROLE_CODE_ARCHITECT,
    ROLE_CODE_CTO,
    ROLE_CODE_TECHLEAD,
    ROLE_CODE_UNASSIGNED,
)

SUMMARY_URL = "/api/v1/roles/summary"

MONDAY = date(2026, 8, 24)
SUNDAY = MONDAY + timedelta(days=6)

# Сорок часов недели и сорок минут архитектуры в них — ровно тот перекос,
# ради обнаружения которого всё и затевалось.
WEEK_MINUTES = 40 * 60
ARCHITECT_MINUTES = 40


@pytest.fixture(autouse=True)
async def roles(db_session: AsyncSession) -> None:
    """Справочник ролей, которого у базы из `create_all` нет."""
    await role_crud.seed_roles(db_session)
    await db_session.commit()


async def add_minutes(
    db: AsyncSession, on: date, code: str, minutes: int, *, ref: str | None = None
) -> None:
    """Минуты роли одним днём — тем же путём, которым их пишет форма."""
    role = await role_crud.get_role_by_code(db, code)
    assert role is not None
    await role_crud.write_time_block(
        db,
        role_crud.TimeBlockDraft(
            work_day=on, role_id=role.id, minutes=minutes, external_ref=ref
        ),
    )
    await db.commit()


async def add_act(db: AsyncSession, on: date, code: str, kind: str, title: str) -> None:
    """Акт роли одним днём."""
    role = await role_crud.get_role_by_code(db, code)
    assert role is not None
    await role_crud.write_act(
        db,
        role_crud.ActDraft(work_day=on, role_id=role.id, act_kind=kind, title=title),
    )
    await db.commit()


def slice_of(summary: Any, code: str) -> Any:
    """Одна строка свёртки по коду роли."""
    return next(one for one in summary.roles if one.role_code == code)


@pytest.mark.asyncio
class TestTheFold:
    """Доли считаются от суммы рабочих минут, и `unassigned` в знаменателе."""

    async def test_shares_are_counted_over_the_whole_week(
        self, db_session: AsyncSession
    ) -> None:
        await add_minutes(db_session, MONDAY, ROLE_CODE_TECHLEAD, 600)
        await add_minutes(db_session, MONDAY + timedelta(days=1), ROLE_CODE_CTO, 200)
        await add_minutes(
            db_session, MONDAY + timedelta(days=2), ROLE_CODE_UNASSIGNED, 200
        )

        summary = await role_crud.role_summary(db_session, MONDAY, SUNDAY)

        assert summary.total_minutes == 1000
        assert slice_of(summary, ROLE_CODE_TECHLEAD).share_pct == 60
        assert slice_of(summary, ROLE_CODE_CTO).share_pct == 20
        # `unassigned` входит в знаменатель: доля тимлида 60%, а не 75%.
        assert summary.unassigned_share_pct == 20

    async def test_the_gap_from_the_target_is_computed_by_the_server(
        self, db_session: AsyncSession
    ) -> None:
        """Отклонение считает сервер: второе вычитание разошлось бы с первым."""
        await add_minutes(db_session, MONDAY, ROLE_CODE_TECHLEAD, 900)
        await add_minutes(db_session, MONDAY, ROLE_CODE_CTO, 100)

        summary = await role_crud.role_summary(db_session, MONDAY, SUNDAY)

        techlead = slice_of(summary, ROLE_CODE_TECHLEAD)
        assert (techlead.share_pct, techlead.target_share_pct) == (90, 50)
        assert techlead.delta_pct == 40
        assert slice_of(summary, ROLE_CODE_CTO).delta_pct == -15

    async def test_unassigned_has_no_target_and_therefore_no_gap(
        self, db_session: AsyncSession
    ) -> None:
        """Целиться в долю неотнесённой работы значит целиться не в то."""
        await add_minutes(db_session, MONDAY, ROLE_CODE_UNASSIGNED, 100)

        summary = await role_crud.role_summary(db_session, MONDAY, SUNDAY)

        assert slice_of(summary, ROLE_CODE_UNASSIGNED).target_share_pct is None
        assert slice_of(summary, ROLE_CODE_UNASSIGNED).delta_pct is None

    async def test_an_empty_week_is_an_empty_summary_not_a_zero(
        self, db_session: AsyncSession
    ) -> None:
        """Приёмка: пустая неделя — не ошибка и не деление на ноль."""
        summary = await role_crud.role_summary(db_session, MONDAY, SUNDAY)

        assert summary.total_minutes == 0
        assert all(one.share_pct == 0 for one in summary.roles)
        assert summary.unassigned_share_pct == 0
        assert summary.rules_lag is False

    async def test_forty_minutes_of_architecture_in_forty_hours_show_as_a_number(
        self, db_session: AsyncSession
    ) -> None:
        """Приёмка: перекос виден числом, а не прячется за дневными клаузами."""
        await add_minutes(
            db_session, MONDAY, ROLE_CODE_TECHLEAD, WEEK_MINUTES - ARCHITECT_MINUTES
        )
        await add_minutes(db_session, MONDAY, ROLE_CODE_ARCHITECT, ARCHITECT_MINUTES)
        # Дневной клауз при этом закрывался: акт архитектора был каждый день.
        for day in range(5):
            await add_act(
                db_session,
                MONDAY + timedelta(days=day),
                ROLE_CODE_ARCHITECT,
                "adr_written",
                f"ADR дня {day}",
            )

        summary = await role_crud.role_summary(db_session, MONDAY, SUNDAY)

        architect = slice_of(summary, ROLE_CODE_ARCHITECT)
        assert architect.minutes == ARCHITECT_MINUTES
        assert architect.share_pct == 2
        assert architect.delta_pct == -23
        # Акты при этом закрывались каждый день — вот и вырождение в ритуал.
        assert architect.act_total == 5


@pytest.mark.asyncio
class TestActsByKind:
    """Счётчик по видам — вторая половина картины."""

    async def test_acts_are_counted_by_kind_and_by_role(
        self, db_session: AsyncSession
    ) -> None:
        await add_act(db_session, MONDAY, ROLE_CODE_CTO, "budget_decision", "бюджет")
        await add_act(db_session, MONDAY, ROLE_CODE_CTO, "hiring_step", "найм")
        await add_act(
            db_session, SUNDAY, ROLE_CODE_CTO, "budget_decision", "бюджет ещё раз"
        )
        await add_act(db_session, MONDAY, ROLE_CODE_ARCHITECT, "adr_written", "ADR")

        summary = await role_crud.role_summary(db_session, MONDAY, SUNDAY)

        cto = slice_of(summary, ROLE_CODE_CTO)
        assert cto.act_counts == {"budget_decision": 2, "hiring_step": 1}
        assert cto.act_total == 3
        assert slice_of(summary, ROLE_CODE_ARCHITECT).act_total == 1

    async def test_an_act_outside_the_period_is_not_counted(
        self, db_session: AsyncSession
    ) -> None:
        await add_act(
            db_session, SUNDAY + timedelta(days=1), ROLE_CODE_CTO, "hiring_step", "найм"
        )

        summary = await role_crud.role_summary(db_session, MONDAY, SUNDAY)

        assert slice_of(summary, ROLE_CODE_CTO).act_total == 0


@pytest.mark.asyncio
class TestTheLagSignal:
    """Порог тридцати процентов — на границе, а не около неё."""

    async def _window(self, db: AsyncSession, unassigned: int, other: int) -> Any:
        """Окно в тридцать дней с известной долей `unassigned`."""
        await add_minutes(db, SUNDAY, ROLE_CODE_UNASSIGNED, unassigned)
        await add_minutes(db, SUNDAY, ROLE_CODE_TECHLEAD, other)
        return await role_crud.role_summary(db, MONDAY, SUNDAY)

    async def test_twenty_nine_percent_stays_silent(
        self, db_session: AsyncSession
    ) -> None:
        """Приёмка: на 29% экран молчит."""
        summary = await self._window(db_session, 290, 710)

        assert summary.window_unassigned_share_pct == 29
        assert summary.rules_lag is False

    async def test_thirty_percent_exactly_stays_silent(
        self, db_session: AsyncSession
    ) -> None:
        """Порог — «выше тридцати», и ровно тридцать его не переходит."""
        summary = await self._window(db_session, 300, 700)

        assert summary.window_unassigned_share_pct == 30
        assert summary.rules_lag is False

    async def test_thirty_one_percent_raises_the_flag(
        self, db_session: AsyncSession
    ) -> None:
        """Приёмка: на 31% экран прямо говорит, что правила отстали."""
        summary = await self._window(db_session, 310, 690)

        assert summary.window_unassigned_share_pct == 31
        assert summary.rules_lag is True

    async def test_the_flag_is_decided_on_the_ratio_not_the_rounded_percent(
        self, db_session: AsyncSession
    ) -> None:
        """
        30,1% поднимает флаг, хотя показывается как «30».

        Сравнение округлённых процентов пропустило бы этот случай молча — то
        есть сигнал, объявленный заранее и в ADR, и на экране, не сработал бы
        ровно там, где он и должен впервые сработать.
        """
        summary = await self._window(db_session, 301, 699)

        assert summary.window_unassigned_share_pct == 30
        assert summary.rules_lag is True

    async def test_minutes_outside_the_window_do_not_move_the_flag(
        self, db_session: AsyncSession
    ) -> None:
        """Окно скользящее: то, что старше тридцати дней, в него не входит."""
        old = SUNDAY - timedelta(days=60)
        await add_minutes(db_session, old, ROLE_CODE_UNASSIGNED, 10_000)
        summary = await self._window(db_session, 100, 900)

        assert summary.window_unassigned_share_pct == 10
        assert summary.rules_lag is False


@pytest.mark.asyncio
class TestTheMarkdownBlock:
    """`format=md` — тот же расчёт, отрендеренный, а не второй расчёт."""

    async def test_the_text_carries_the_same_numbers_as_the_json(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Приёмка: числа в тексте совпадают с числами JSON за тот же период."""
        await add_minutes(db_session, MONDAY, ROLE_CODE_TECHLEAD, 900)
        await add_minutes(db_session, MONDAY, ROLE_CODE_CTO, 100)
        params = {"date_from": MONDAY.isoformat(), "date_to": SUNDAY.isoformat()}

        as_json = await client.get(SUMMARY_URL, params=params)
        as_md = await client.get(SUMMARY_URL, params={**params, "format": "md"})

        assert as_json.status_code == 200, as_json.text
        assert as_md.status_code == 200, as_md.text
        body = as_json.json()
        text = as_md.text
        assert body["markdown"] == text
        for one in body["roles"]:
            if one["minutes"] == 0:
                continue
            assert f"{one['share_pct']}%" in text
            if one["delta_pct"] is not None:
                assert f"{one['delta_pct']:+d} п.п." in text

    async def test_the_block_says_the_targets_are_a_hypothesis(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Подпись уезжает в отчёт вместе с числом, а не остаётся на экране."""
        await add_minutes(db_session, MONDAY, ROLE_CODE_CTO, 100)

        response = await client.get(
            SUMMARY_URL,
            params={
                "date_from": MONDAY.isoformat(),
                "date_to": SUNDAY.isoformat(),
                "format": "md",
            },
        )

        assert TARGET_NOTE in response.text

    async def test_an_empty_period_renders_words_not_zeros(
        self, db_session: AsyncSession
    ) -> None:
        summary = await role_crud.role_summary(db_session, MONDAY, SUNDAY)

        text = render_summary_md(summary)

        assert NO_DATA_LINE in text
        assert "0%" not in text

    async def test_a_period_without_acts_says_so(
        self, db_session: AsyncSession
    ) -> None:
        await add_minutes(db_session, MONDAY, ROLE_CODE_CTO, 100)

        text = render_summary_md(
            await role_crud.role_summary(db_session, MONDAY, SUNDAY)
        )

        assert NO_ACTS_LINE in text

    async def test_the_lag_sentence_appears_only_when_the_flag_is_up(
        self, db_session: AsyncSession
    ) -> None:
        await add_minutes(db_session, SUNDAY, ROLE_CODE_UNASSIGNED, 310)
        await add_minutes(db_session, SUNDAY, ROLE_CODE_TECHLEAD, 690)

        text = render_summary_md(
            await role_crud.role_summary(db_session, MONDAY, SUNDAY)
        )

        assert "Правила разметки отстали" in text
        assert "ADR-0020" in text


@pytest.mark.asyncio
class TestTheEndpoint:
    """Один эндпоинт на неделю и на месяц, без второй реализации."""

    async def test_a_month_is_the_same_endpoint(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Приёмка: сводка за месяц считается тем же эндпоинтом."""
        await add_minutes(db_session, MONDAY, ROLE_CODE_CTO, 100)
        await add_minutes(db_session, MONDAY - timedelta(days=20), ROLE_CODE_CTO, 300)

        response = await client.get(
            SUMMARY_URL,
            params={
                "date_from": (MONDAY - timedelta(days=30)).isoformat(),
                "date_to": SUNDAY.isoformat(),
            },
        )

        assert response.status_code == 200, response.text
        assert response.json()["total_minutes"] == 400

    async def test_an_unknown_format_is_refused(self, client: AsyncClient) -> None:
        response = await client.get(
            SUMMARY_URL,
            params={
                "date_from": MONDAY.isoformat(),
                "date_to": SUNDAY.isoformat(),
                "format": "csv",
            },
        )

        assert response.status_code == 422

    async def test_a_backwards_period_is_refused(self, client: AsyncClient) -> None:
        response = await client.get(
            SUMMARY_URL,
            params={
                "date_from": SUNDAY.isoformat(),
                "date_to": MONDAY.isoformat(),
            },
        )

        assert response.status_code == 422

    async def test_the_threshold_travels_with_the_answer(
        self, client: AsyncClient
    ) -> None:
        """Порог называет сервер: экран не должен знать его своим числом."""
        response = await client.get(
            SUMMARY_URL,
            params={"date_from": MONDAY.isoformat(), "date_to": SUNDAY.isoformat()},
        )

        assert response.json()["lag_threshold_pct"] == role_crud.UNASSIGNED_LAG_PCT
