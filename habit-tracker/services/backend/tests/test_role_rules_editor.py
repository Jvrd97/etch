"""
Правила разметки правятся в вебе: прогон без записи, переразметка задним числом.

Здесь проверяется то, без чего таблица правил остаётся обещанием. Что сухой
прогон не пишет в базу ни одной строки — проверяется счётом строк до и после, а
не обещанием. Что прогон говорит не только «сколько зацепило», но и «у какого
правила отобрано»: правило, ловящее сто строк, из которых девяносто уже
размечены верно, разметку не улучшает. Что переразметка месяца двигает доли и не
трогает ни одной записи, подтверждённой человеком. Что правило с меньшим
`priority` выигрывает у существующего на той же разметке. И что удаление роли,
на которую ссылается правило, отвергает база, а не проверка в сервисе.
"""

# [review:need-review] PHASE-03/139
# summary: tests for the rules editor — the dry run writing nothing at all, the counters naming the rule a match is taken from, an empty history reported as scanned rows rather than as «правило не ловит», re-markup moving the shares while leaving every `confirmed` row alone, a smaller priority winning on the same day, and the database refusing to delete a role a rule points at
from datetime import date, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.daytime import today_local
from app.crud import role as role_crud
from app.models.role import (
    CONFIDENCE_CONFIRMED,
    MATCHER_COMMIT_PREFIX,
    MATCHER_WINDOW_TITLE_REGEX,
    ROLE_CODE_ARCHITECT,
    ROLE_CODE_CTO,
    ROLE_CODE_TECHLEAD,
    ROLE_CODE_UNASSIGNED,
    SOURCE_GIT,
    RoleAct,
    RoleTimeBlock,
)
from app.roles import classify

RULES_URL = "/api/v1/role-rules"
DRY_RUN_URL = f"{RULES_URL}/dry-run"
RECLASSIFY_URL = "/api/v1/roles/reclassify"
ROLES_URL = "/api/v1/roles"

TODAY = today_local()
YESTERDAY = TODAY - timedelta(days=1)
MONTH_AGO = TODAY - timedelta(days=29)


@pytest.fixture(autouse=True)
async def roles(db_session: AsyncSession) -> None:
    """Справочник ролей, которого у базы из `create_all` нет."""
    await role_crud.seed_roles(db_session)
    await db_session.commit()


async def role_id(db: AsyncSession, code: str) -> int:
    role = await role_crud.get_role_by_code(db, code)
    assert role is not None
    return role.id


async def add_block(
    db: AsyncSession,
    on: date,
    code: str,
    note: str,
    *,
    minutes: int = 60,
    confirmed: bool = False,
    rule_id: int | None = None,
    ref: str | None = None,
) -> RoleTimeBlock:
    """Минуты, записанные автоматическим источником, с образцом в записке."""
    outcome = await role_crud.write_time_block(
        db,
        role_crud.TimeBlockDraft(
            work_day=on,
            role_id=await role_id(db, code),
            minutes=minutes,
            source=SOURCE_GIT,
            note=note,
            rule_id=rule_id,
            external_ref=ref,
            confidence=CONFIDENCE_CONFIRMED if confirmed else "auto",
        ),
    )
    await db.commit()
    return outcome.row


async def add_auto_act(
    db: AsyncSession, on: date, code: str, title: str, *, confirmed: bool = False
) -> RoleAct:
    """Акт, записанный автоматическим источником."""
    outcome = await role_crud.write_act(
        db,
        role_crud.ActDraft(
            work_day=on,
            role_id=await role_id(db, code),
            act_kind="adr_written",
            title=title,
            source=SOURCE_GIT,
            confidence=CONFIDENCE_CONFIRMED if confirmed else "auto",
        ),
    )
    await db.commit()
    return outcome.row


async def add_rule(
    client: AsyncClient, code: str, pattern: str, *, priority: int = 100
) -> dict[str, Any]:
    """Правило разметки заводится с экрана — то есть запросом, без SQL."""
    response = await client.post(
        RULES_URL,
        json={
            "role_code": code,
            "source": SOURCE_GIT,
            "matcher_kind": MATCHER_COMMIT_PREFIX,
            "pattern": pattern,
            "priority": priority,
        },
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


async def row_counts(db: AsyncSession) -> tuple[int, int, int]:
    """Сколько строк в трёх таблицах, которых прогон касаться не должен."""
    return (
        int(await db.scalar(select(func.count(RoleTimeBlock.id))) or 0),
        int(await db.scalar(select(func.count(RoleAct.id))) or 0),
        len(await role_crud.list_rules(db, active_only=False)),
    )


@pytest.mark.asyncio
class TestTheRulesScreen:
    """Правило заводится с экрана и начинает действовать на следующей разметке."""

    async def test_a_rule_is_created_without_sql_and_applies_next_time(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await add_block(db_session, TODAY, ROLE_CODE_UNASSIGNED, "feat(api): ручка")
        await add_rule(client, ROLE_CODE_TECHLEAD, "feat(")

        response = await client.post(
            RECLASSIFY_URL,
            json={"date_from": TODAY.isoformat(), "date_to": TODAY.isoformat()},
        )

        assert response.status_code == 200, response.text
        assert response.json()["changed_time_blocks"] == 1

    async def test_the_list_is_ordered_the_way_the_resolver_picks(
        self, client: AsyncClient
    ) -> None:
        """Сильные первыми — тем же порядком, которым выбирается победитель."""
        await add_rule(client, ROLE_CODE_CTO, "chore(", priority=50)
        await add_rule(client, ROLE_CODE_TECHLEAD, "feat(", priority=10)

        listing = (await client.get(RULES_URL)).json()

        assert [one["priority"] for one in listing] == [10, 50]


@pytest.mark.asyncio
class TestDryRun:
    """Прогон до сохранения: сколько зацепит и у кого отберёт."""

    async def test_the_dry_run_writes_nothing_at_all(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Приёмка: проверяется счётом строк, а не обещанием."""
        await add_block(db_session, TODAY, ROLE_CODE_UNASSIGNED, "feat(api): ручка")
        before = await row_counts(db_session)

        response = await client.post(
            DRY_RUN_URL,
            json={
                "role_code": ROLE_CODE_TECHLEAD,
                "source": SOURCE_GIT,
                "matcher_kind": MATCHER_COMMIT_PREFIX,
                "pattern": "feat(",
            },
        )

        assert response.status_code == 200, response.text
        assert response.json()["matched_time_blocks"] == 1
        assert await row_counts(db_session) == before

    async def test_it_counts_intervals_and_acts_apart(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """«Сколько интервалов и актов» — два числа, а не одно."""
        await add_block(db_session, TODAY, ROLE_CODE_UNASSIGNED, "feat(api): ручка")
        await add_block(db_session, YESTERDAY, ROLE_CODE_UNASSIGNED, "feat(ui): экран")
        await add_auto_act(db_session, TODAY, ROLE_CODE_UNASSIGNED, "feat(adr): ADR")

        response = await client.post(
            DRY_RUN_URL,
            json={
                "role_code": ROLE_CODE_TECHLEAD,
                "source": SOURCE_GIT,
                "matcher_kind": MATCHER_COMMIT_PREFIX,
                "pattern": "feat(",
            },
        )

        body = response.json()
        assert (body["matched_time_blocks"], body["matched_acts"]) == (2, 1)
        assert body["scanned_rows"] == 3

    async def test_it_names_the_rule_it_takes_matches_from(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Приёмка: у какого правила новое отбирает совпадения."""
        existing = await add_rule(client, ROLE_CODE_CTO, "feat(", priority=50)
        await add_block(
            db_session,
            TODAY,
            ROLE_CODE_CTO,
            "feat(api): ручка",
            rule_id=existing["id"],
        )

        response = await client.post(
            DRY_RUN_URL,
            json={
                "role_code": ROLE_CODE_TECHLEAD,
                "source": SOURCE_GIT,
                "matcher_kind": MATCHER_COMMIT_PREFIX,
                "pattern": "feat(",
                "priority": 10,
            },
        )

        body = response.json()
        assert body["taken_from"] == {str(existing["id"]): 1}
        assert body["taken_from_nobody"] == 0

    async def test_an_empty_history_says_how_much_it_scanned(
        self, client: AsyncClient
    ) -> None:
        """
        Ноль на пустой истории и ноль на месяце данных — разные ответы.

        Без `scanned_rows` первый читался бы как «правило не ловит», и человек
        переписывал бы работающее правило.
        """
        response = await client.post(
            DRY_RUN_URL,
            json={
                "role_code": ROLE_CODE_TECHLEAD,
                "source": SOURCE_GIT,
                "matcher_kind": MATCHER_COMMIT_PREFIX,
                "pattern": "feat(",
            },
        )

        body = response.json()
        assert body["scanned_rows"] == 0
        assert body["matched_time_blocks"] == 0

    async def test_examples_show_what_matched(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await add_block(db_session, TODAY, ROLE_CODE_UNASSIGNED, "feat(api): ручка")

        response = await client.post(
            DRY_RUN_URL,
            json={
                "role_code": ROLE_CODE_TECHLEAD,
                "source": SOURCE_GIT,
                "matcher_kind": MATCHER_COMMIT_PREFIX,
                "pattern": "feat(",
            },
        )

        examples = response.json()["examples"]
        assert len(examples) == 1
        assert examples[0]["label"] == "feat(api): ручка"
        assert examples[0]["kind"] == "time_block"

    async def test_a_broken_regex_is_refused_before_the_run(
        self, client: AsyncClient
    ) -> None:
        """Прогон отвергает ровно то, что отвергнет сохранение."""
        response = await client.post(
            DRY_RUN_URL,
            json={
                "role_code": ROLE_CODE_TECHLEAD,
                "source": SOURCE_GIT,
                "matcher_kind": MATCHER_WINDOW_TITLE_REGEX,
                "pattern": "([",
            },
        )

        assert response.status_code == 422

    async def test_a_row_outside_the_window_is_not_scanned(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await add_block(
            db_session,
            TODAY - timedelta(days=40),
            ROLE_CODE_UNASSIGNED,
            "feat(api): старое",
        )

        response = await client.post(
            DRY_RUN_URL,
            json={
                "role_code": ROLE_CODE_TECHLEAD,
                "source": SOURCE_GIT,
                "matcher_kind": MATCHER_COMMIT_PREFIX,
                "pattern": "feat(",
                "days_back": 30,
            },
        )

        assert response.json()["scanned_rows"] == 0


@pytest.mark.asyncio
class TestReclassify:
    """Переразметка двигает доли и не трогает подтверждённое человеком."""

    async def test_a_month_moves_the_shares_and_shows_before_and_after(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Приёмка: доли меняются, и обе половины видно в одном ответе."""
        await add_block(
            db_session, MONTH_AGO, ROLE_CODE_UNASSIGNED, "feat(api): ручка", ref="a"
        )
        await add_block(
            db_session, TODAY, ROLE_CODE_UNASSIGNED, "feat(ui): экран", ref="b"
        )
        await add_rule(client, ROLE_CODE_TECHLEAD, "feat(")

        response = await client.post(
            RECLASSIFY_URL,
            json={"date_from": MONTH_AGO.isoformat(), "date_to": TODAY.isoformat()},
        )

        body = response.json()
        techlead = await role_id(db_session, ROLE_CODE_TECHLEAD)
        unassigned = await role_id(db_session, ROLE_CODE_UNASSIGNED)
        before = {one["role_id"]: one["share_pct"] for one in body["before"]}
        after = {one["role_id"]: one["share_pct"] for one in body["after"]}

        assert before[unassigned] == 100
        assert after[techlead] == 100
        assert body["changed_time_blocks"] == 2

    async def test_a_confirmed_row_is_never_touched_and_is_counted(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Приёмка: подтверждённое человеком не меняется, и число названо."""
        confirmed = await add_block(
            db_session,
            TODAY,
            ROLE_CODE_CTO,
            "feat(api): это я поправил руками",
            confirmed=True,
            ref="confirmed",
        )
        await add_block(
            db_session, TODAY, ROLE_CODE_UNASSIGNED, "feat(ui): экран", ref="auto"
        )
        await add_rule(client, ROLE_CODE_TECHLEAD, "feat(")

        response = await client.post(
            RECLASSIFY_URL,
            json={"date_from": TODAY.isoformat(), "date_to": TODAY.isoformat()},
        )

        assert response.json()["protected"] == 1
        assert response.json()["changed_time_blocks"] == 1
        await db_session.refresh(confirmed)
        assert confirmed.role_id == await role_id(db_session, ROLE_CODE_CTO)

    async def test_a_confirmed_act_is_left_alone_too(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        act = await add_auto_act(
            db_session, TODAY, ROLE_CODE_CTO, "feat(adr): мой акт", confirmed=True
        )
        await add_rule(client, ROLE_CODE_ARCHITECT, "feat(")

        await client.post(
            RECLASSIFY_URL,
            json={"date_from": TODAY.isoformat(), "date_to": TODAY.isoformat()},
        )

        await db_session.refresh(act)
        assert act.role_id == await role_id(db_session, ROLE_CODE_CTO)

    async def test_a_manual_row_is_outside_the_markup_entirely(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Роль, выбранная человеком, правилом не переписывается — и не считается."""
        manual = await role_crud.write_time_block(
            db_session,
            role_crud.TimeBlockDraft(
                work_day=TODAY,
                role_id=await role_id(db_session, ROLE_CODE_CTO),
                minutes=90,
                note="feat(api): полтора часа на найм",
            ),
        )
        await db_session.commit()
        await add_rule(client, ROLE_CODE_TECHLEAD, "feat(")

        response = await client.post(
            RECLASSIFY_URL,
            json={"date_from": TODAY.isoformat(), "date_to": TODAY.isoformat()},
        )

        assert response.json()["scanned_rows"] == 0
        await db_session.refresh(manual.row)
        assert manual.row.role_id == await role_id(db_session, ROLE_CODE_CTO)

    async def test_an_empty_period_is_an_answer_not_an_error(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            RECLASSIFY_URL,
            json={"date_from": TODAY.isoformat(), "date_to": TODAY.isoformat()},
        )

        assert response.status_code == 200, response.text
        assert response.json()["scanned_rows"] == 0
        assert response.json()["before"] == []

    async def test_a_backwards_period_is_refused(self, client: AsyncClient) -> None:
        response = await client.post(
            RECLASSIFY_URL,
            json={"date_from": TODAY.isoformat(), "date_to": MONTH_AGO.isoformat()},
        )

        assert response.status_code == 422

    async def test_a_row_nothing_matches_lands_on_unassigned(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Промах — это `unassigned`, а не NULL и не прежняя роль наугад."""
        block = await add_block(
            db_session, TODAY, ROLE_CODE_CTO, "chore(deps): бамп", ref="miss"
        )
        await add_rule(client, ROLE_CODE_TECHLEAD, "feat(")

        await client.post(
            RECLASSIFY_URL,
            json={"date_from": TODAY.isoformat(), "date_to": TODAY.isoformat()},
        )

        await db_session.refresh(block)
        assert block.role_id == await role_id(db_session, ROLE_CODE_UNASSIGNED)


@pytest.mark.asyncio
class TestPriority:
    """Меньший `priority` выигрывает — и это видно на разметке того же дня."""

    async def test_a_stronger_rule_wins_on_the_same_day(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Приёмка: видно в разметке, а не только в тесте резолвера."""
        await add_rule(client, ROLE_CODE_CTO, "feat(", priority=50)
        block = await add_block(
            db_session, TODAY, ROLE_CODE_UNASSIGNED, "feat(api): ручка", ref="one"
        )
        await client.post(
            RECLASSIFY_URL,
            json={"date_from": TODAY.isoformat(), "date_to": TODAY.isoformat()},
        )
        await db_session.refresh(block)
        assert block.role_id == await role_id(db_session, ROLE_CODE_CTO)

        await add_rule(client, ROLE_CODE_TECHLEAD, "feat(", priority=10)
        await client.post(
            RECLASSIFY_URL,
            json={"date_from": TODAY.isoformat(), "date_to": TODAY.isoformat()},
        )

        await db_session.refresh(block)
        assert block.role_id == await role_id(db_session, ROLE_CODE_TECHLEAD)


@pytest.mark.asyncio
class TestDeletingARole:
    """Роль, на которую ссылается правило, удаляет не сервис, а база."""

    async def test_the_database_refuses_to_delete_a_referenced_role(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Приёмка: отказ приходит от `ON DELETE RESTRICT`, а не от проверки."""
        await add_rule(client, ROLE_CODE_TECHLEAD, "feat(")
        target = await role_id(db_session, ROLE_CODE_TECHLEAD)

        response = await client.delete(f"{ROLES_URL}/{target}")

        assert response.status_code == 422, response.text
        assert await role_crud.get_role(db_session, target) is not None

    async def test_a_role_nothing_points_at_is_removed(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        role = await role_crud.create_role(
            db_session, code="temp", title="Временная роль"
        )
        await db_session.commit()

        response = await client.delete(f"{ROLES_URL}/{role.id}")

        assert response.status_code == 204, response.text


@pytest.mark.asyncio
class TestTheServiceLayer:
    """Прогон и переразметка — функции над строками, а не над ручкой."""

    async def test_dry_run_is_pure_of_writes_at_the_service_level_too(
        self, db_session: AsyncSession
    ) -> None:
        await add_block(db_session, TODAY, ROLE_CODE_UNASSIGNED, "feat(api): ручка")
        before = await row_counts(db_session)

        await classify.dry_run(
            db_session,
            role_id=await role_id(db_session, ROLE_CODE_TECHLEAD),
            source=SOURCE_GIT,
            matcher_kind=MATCHER_COMMIT_PREFIX,
            pattern="feat(",
            priority=100,
            date_from=MONTH_AGO,
            date_to=TODAY,
        )

        assert await row_counts(db_session) == before
