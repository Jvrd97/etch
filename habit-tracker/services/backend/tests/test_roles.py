# [review:need-review] PHASE-03/134
# summary: integration tests of the roles — a manual «90 минут, архитектор, найм» shows up in the day at once, a sample nothing matched is charged to `unassigned` and never to NULL, a re-imported `(source, external_ref)` does not double the day, a `confirmed` row survives the importer untouched, zero minutes is refused by the table's CHECK rather than by a service, and a day carrying one architect act reads differently from a day with none
"""
Tests of the role vertical.

The pure order of the rules lives in `test_role_matcher.py`. What is checked
here is everything that needs a table: the seed, the fallback to `unassigned`,
idempotency on `(source, external_ref)`, the `confirmed` guard and the refusal
of zero minutes by the database itself.
"""

from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import role as role_crud
from app.models.role import (
    CONFIDENCE_AUTO,
    CONFIDENCE_CONFIRMED,
    MATCHER_BUNDLE_ID,
    MATCHER_WINDOW_TITLE_REGEX,
    ROLE_CODE_ARCHITECT,
    ROLE_CODE_CTO,
    ROLE_CODE_TECHLEAD,
    ROLE_CODE_UNASSIGNED,
    SOURCE_APP_USAGE,
    SOURCE_GIT,
    SOURCE_MANUAL,
    Role,
    RoleTimeBlock,
)
from app.roles.catalog import SEED_ROLES
from app.roles.matcher import MatchSample

WORK_DAY = date(2026, 8, 30)
OTHER_DAY = date(2026, 8, 29)


@pytest.fixture(autouse=True)
async def directory(db_session: AsyncSession) -> None:
    """
    Seed the role directory.

    Tests build their schema with `create_all`, which never sees the migration's
    seed, so the same four rows are applied through the shared module rather
    than repeated as literals.
    """
    await role_crud.seed_roles(db_session)
    await db_session.commit()


async def role_id(db_session: AsyncSession, code: str) -> int:
    role = await role_crud.get_role_by_code(db_session, code)
    assert role is not None
    return role.id


class TestSeed:
    async def test_the_four_roles_are_there(self, db_session: AsyncSession) -> None:
        roles = await role_crud.list_roles(db_session)
        assert [role.code for role in roles] == [
            ROLE_CODE_CTO,
            ROLE_CODE_ARCHITECT,
            ROLE_CODE_TECHLEAD,
            ROLE_CODE_UNASSIGNED,
        ]

    async def test_seeding_twice_adds_nothing(self, db_session: AsyncSession) -> None:
        """The seed runs on a filled directory as happily as on an empty one."""
        await role_crud.seed_roles(db_session)
        await db_session.commit()
        count = (
            await db_session.execute(select(func.count()).select_from(Role))
        ).scalar_one()
        assert count == len(SEED_ROLES)

    async def test_the_target_share_is_carried_but_unassigned_has_none(
        self, db_session: AsyncSession
    ) -> None:
        """The hypothesis is 25/25/50; aiming at unattributed work is not a goal."""
        roles = {role.code: role for role in await role_crud.list_roles(db_session)}
        assert roles[ROLE_CODE_CTO].target_share_pct == 25
        assert roles[ROLE_CODE_ARCHITECT].target_share_pct == 25
        assert roles[ROLE_CODE_TECHLEAD].target_share_pct == 50
        assert roles[ROLE_CODE_UNASSIGNED].target_share_pct is None


class TestResolution:
    async def test_a_sample_nothing_matched_is_unassigned_not_null(
        self, db_session: AsyncSession
    ) -> None:
        """
        The acceptance case: «не удалось отнести» is a row, not a NULL.

        The block is written with the resolved role, and the table is then
        checked for `role_id IS NULL` — the state this design exists to make
        unreachable.
        """
        resolution = await role_crud.resolve_role(
            db_session,
            MatchSample(
                source=SOURCE_APP_USAGE,
                bundle_id="com.apple.Safari",
                window_title="что-то, о чём правил нет",
            ),
        )
        assert resolution.matched is False
        assert resolution.rule_id is None
        assert resolution.role_id == await role_id(db_session, ROLE_CODE_UNASSIGNED)

        await role_crud.write_time_block(
            db_session,
            role_crud.TimeBlockDraft(
                work_day=WORK_DAY,
                role_id=resolution.role_id,
                minutes=25,
                source=SOURCE_APP_USAGE,
                external_ref="interval-1",
            ),
        )
        await db_session.commit()

        nulls = (
            await db_session.execute(
                select(func.count())
                .select_from(RoleTimeBlock)
                .where(RoleTimeBlock.role_id.is_(None))
            )
        ).scalar_one()
        assert nulls == 0

    async def test_the_stronger_rule_decides_through_the_database(
        self, db_session: AsyncSession
    ) -> None:
        """The conflict of two stored rules resolves the same way the pure one does."""
        await role_crud.create_rule(
            db_session,
            role_id=await role_id(db_session, ROLE_CODE_TECHLEAD),
            source=SOURCE_APP_USAGE,
            matcher_kind=MATCHER_BUNDLE_ID,
            pattern="com.microsoft.VSCode",
            priority=100,
        )
        await role_crud.create_rule(
            db_session,
            role_id=await role_id(db_session, ROLE_CODE_ARCHITECT),
            source=SOURCE_APP_USAGE,
            matcher_kind=MATCHER_WINDOW_TITLE_REGEX,
            pattern=r"^ADR-\d+",
            priority=10,
        )
        await db_session.commit()

        resolution = await role_crud.resolve_role(
            db_session,
            MatchSample(
                source=SOURCE_APP_USAGE,
                bundle_id="com.microsoft.VSCode",
                window_title="ADR-0020-healthkit-and-cto-metrics.md",
            ),
        )
        assert resolution.matched is True
        assert resolution.role_id == await role_id(db_session, ROLE_CODE_ARCHITECT)

    async def test_an_inactive_rule_does_not_decide(
        self, db_session: AsyncSession
    ) -> None:
        await role_crud.create_rule(
            db_session,
            role_id=await role_id(db_session, ROLE_CODE_CTO),
            source=SOURCE_APP_USAGE,
            matcher_kind=MATCHER_BUNDLE_ID,
            pattern="com.apple.Safari",
            priority=1,
            is_active=False,
        )
        await db_session.commit()
        resolution = await role_crud.resolve_role(
            db_session,
            MatchSample(source=SOURCE_APP_USAGE, bundle_id="com.apple.Safari"),
        )
        assert resolution.matched is False


class TestIdempotency:
    async def test_the_same_external_ref_does_not_double_the_day(
        self, db_session: AsyncSession
    ) -> None:
        """The importer runs twice; the day is stated twice, not counted twice."""
        architect = await role_id(db_session, ROLE_CODE_ARCHITECT)
        draft = role_crud.TimeBlockDraft(
            work_day=WORK_DAY,
            role_id=architect,
            minutes=40,
            source=SOURCE_GIT,
            external_ref="9f1c2b7",
        )
        first = await role_crud.write_time_block(db_session, draft)
        second = await role_crud.write_time_block(db_session, draft)
        await db_session.commit()

        assert first.created is True
        assert second.created is False
        assert second.row.id == first.row.id

        blocks = await role_crud.day_time_blocks(db_session, WORK_DAY)
        assert len(blocks) == 1
        assert sum(block.minutes for block in blocks) == 40

    async def test_a_second_pass_restates_the_row(
        self, db_session: AsyncSession
    ) -> None:
        """A corrected import overwrites its own row rather than adding one."""
        architect = await role_id(db_session, ROLE_CODE_ARCHITECT)
        await role_crud.write_time_block(
            db_session,
            role_crud.TimeBlockDraft(
                work_day=WORK_DAY,
                role_id=architect,
                minutes=40,
                source=SOURCE_GIT,
                external_ref="9f1c2b7",
            ),
        )
        await role_crud.write_time_block(
            db_session,
            role_crud.TimeBlockDraft(
                work_day=WORK_DAY,
                role_id=architect,
                minutes=55,
                source=SOURCE_GIT,
                external_ref="9f1c2b7",
            ),
        )
        await db_session.commit()
        blocks = await role_crud.day_time_blocks(db_session, WORK_DAY)
        assert [block.minutes for block in blocks] == [55]

    async def test_manual_records_without_a_ref_are_never_folded(
        self, db_session: AsyncSession
    ) -> None:
        """Two honest ninety-minute records are two records, not a duplicate."""
        cto = await role_id(db_session, ROLE_CODE_CTO)
        for _ in range(2):
            await role_crud.write_time_block(
                db_session,
                role_crud.TimeBlockDraft(
                    work_day=WORK_DAY,
                    role_id=cto,
                    minutes=90,
                    source=SOURCE_MANUAL,
                    note="найм",
                ),
            )
        await db_session.commit()
        blocks = await role_crud.day_time_blocks(db_session, WORK_DAY)
        assert len(blocks) == 2


class TestConfirmedSurvives:
    async def test_the_importer_does_not_touch_a_confirmed_block(
        self, db_session: AsyncSession
    ) -> None:
        """
        The acceptance case for «ручное поверх автоматики».

        A row a person confirmed keeps its role, its minutes and its note when
        the importer passes over the same `(source, external_ref)` again.
        """
        architect = await role_id(db_session, ROLE_CODE_ARCHITECT)
        techlead = await role_id(db_session, ROLE_CODE_TECHLEAD)
        confirmed = await role_crud.write_time_block(
            db_session,
            role_crud.TimeBlockDraft(
                work_day=WORK_DAY,
                role_id=architect,
                minutes=90,
                source=SOURCE_GIT,
                external_ref="9f1c2b7",
                confidence=CONFIDENCE_CONFIRMED,
                note="это была архитектура, а не ревью",
            ),
        )
        await db_session.commit()

        outcome = await role_crud.write_time_block(
            db_session,
            role_crud.TimeBlockDraft(
                work_day=OTHER_DAY,
                role_id=techlead,
                minutes=15,
                source=SOURCE_GIT,
                external_ref="9f1c2b7",
                confidence=CONFIDENCE_AUTO,
            ),
        )
        await db_session.commit()

        assert outcome.kept_confirmed is True
        assert outcome.row.id == confirmed.row.id
        assert outcome.row.role_id == architect
        assert outcome.row.minutes == 90
        assert outcome.row.work_day == WORK_DAY
        assert outcome.row.note == "это была архитектура, а не ревью"

    async def test_a_person_may_still_overwrite_a_confirmed_block(
        self, db_session: AsyncSession
    ) -> None:
        """Only the importer is held off; the person who confirmed can change it."""
        architect = await role_id(db_session, ROLE_CODE_ARCHITECT)
        await role_crud.write_time_block(
            db_session,
            role_crud.TimeBlockDraft(
                work_day=WORK_DAY,
                role_id=architect,
                minutes=90,
                source=SOURCE_GIT,
                external_ref="9f1c2b7",
                confidence=CONFIDENCE_CONFIRMED,
            ),
        )
        outcome = await role_crud.write_time_block(
            db_session,
            role_crud.TimeBlockDraft(
                work_day=WORK_DAY,
                role_id=architect,
                minutes=120,
                source=SOURCE_GIT,
                external_ref="9f1c2b7",
                confidence=CONFIDENCE_CONFIRMED,
            ),
        )
        await db_session.commit()
        assert outcome.kept_confirmed is False
        assert outcome.row.minutes == 120

    async def test_the_importer_does_not_touch_a_confirmed_act(
        self, db_session: AsyncSession
    ) -> None:
        architect = await role_id(db_session, ROLE_CODE_ARCHITECT)
        techlead = await role_id(db_session, ROLE_CODE_TECHLEAD)
        await role_crud.write_act(
            db_session,
            role_crud.ActDraft(
                work_day=WORK_DAY,
                role_id=architect,
                act_kind="adr_written",
                title="ADR-0020",
                source=SOURCE_GIT,
                external_ref="9f1c2b7",
                confidence=CONFIDENCE_CONFIRMED,
            ),
        )
        await db_session.commit()
        outcome = await role_crud.write_act(
            db_session,
            role_crud.ActDraft(
                work_day=WORK_DAY,
                role_id=techlead,
                act_kind="code_review",
                title="ревью",
                source=SOURCE_GIT,
                external_ref="9f1c2b7",
            ),
        )
        await db_session.commit()
        assert outcome.kept_confirmed is True
        assert outcome.row.role_id == architect
        assert outcome.row.act_kind == "adr_written"


class TestZeroMinutes:
    async def test_the_database_refuses_zero(self, db_session: AsyncSession) -> None:
        """
        `minutes = 0` is refused by the `CHECK`, not by a service.

        The distinction is the acceptance condition: a row inserted by `psql`,
        by an import or by a future writer has to be refused by the same
        authority as one inserted by the form.
        """
        architect = await role_id(db_session, ROLE_CODE_ARCHITECT)
        db_session.add(
            RoleTimeBlock(
                work_day=WORK_DAY,
                role_id=architect,
                source=SOURCE_MANUAL,
                minutes=0,
            )
        )
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await db_session.rollback()

    async def test_the_database_refuses_negative_minutes(
        self, db_session: AsyncSession
    ) -> None:
        architect = await role_id(db_session, ROLE_CODE_ARCHITECT)
        db_session.add(
            RoleTimeBlock(
                work_day=WORK_DAY,
                role_id=architect,
                source=SOURCE_MANUAL,
                minutes=-30,
            )
        )
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await db_session.rollback()


class TestAPI:
    async def test_ninety_minutes_on_hiring_show_up_in_the_day(
        self, client: AsyncClient
    ) -> None:
        """
        «90 минут, архитектор, найм» — заведено руками, видно сразу.

        No rule, no importer, no interval: the acceptance case is that the
        manual path alone is a working system.
        """
        created = await client.post(
            "/api/v1/role-time-blocks",
            json={
                "role_code": ROLE_CODE_ARCHITECT,
                "minutes": 90,
                "work_day": WORK_DAY.isoformat(),
                "note": "найм",
            },
        )
        assert created.status_code == 201
        assert created.json()["is_manual"] is True
        assert created.json()["source"] == SOURCE_MANUAL

        day = await client.get(f"/api/v1/roles/day/{WORK_DAY.isoformat()}")
        assert day.status_code == 200
        payload = day.json()
        assert payload["total_minutes"] == 90
        slices = {one["role_code"]: one for one in payload["roles"]}
        assert slices[ROLE_CODE_ARCHITECT]["minutes"] == 90
        assert slices[ROLE_CODE_ARCHITECT]["share_pct"] == 100
        assert slices[ROLE_CODE_TECHLEAD]["minutes"] == 0
        assert [block["note"] for block in payload["blocks"]] == ["найм"]

    async def test_the_target_share_travels_to_the_screen(
        self, client: AsyncClient
    ) -> None:
        """The hypothesis is on the wire; the screen is what labels it as one."""
        response = await client.get("/api/v1/roles")
        assert response.status_code == 200
        shares = {one["code"]: one["target_share_pct"] for one in response.json()}
        assert shares == {
            ROLE_CODE_CTO: 25,
            ROLE_CODE_ARCHITECT: 25,
            ROLE_CODE_TECHLEAD: 50,
            ROLE_CODE_UNASSIGNED: None,
        }

    async def test_zero_minutes_comes_back_422(self, client: AsyncClient) -> None:
        """The table's refusal reaches the form as a 422 rather than a 500."""
        response = await client.post(
            "/api/v1/role-time-blocks",
            json={"role_code": ROLE_CODE_CTO, "minutes": 0},
        )
        assert response.status_code == 422

    async def test_an_unknown_role_code_comes_back_422(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/role-time-blocks",
            json={"role_code": "designer", "minutes": 30},
        )
        assert response.status_code == 422

    async def test_a_day_with_one_architect_act_differs_from_a_day_without(
        self, client: AsyncClient
    ) -> None:
        """
        The acceptance case for acts: «написал ADR» is visible as a day's fact.

        Kind, title and day, and nothing else required — and the day that
        carries it reads differently from the one that does not.
        """
        empty = await client.get(f"/api/v1/roles/day/{OTHER_DAY.isoformat()}")
        assert empty.json()["acts"] == []
        assert all(one["act_count"] == 0 for one in empty.json()["roles"])

        created = await client.post(
            "/api/v1/role-acts",
            json={
                "role_code": ROLE_CODE_ARCHITECT,
                "act_kind": "adr_written",
                "title": "ADR-0020: роли как измеряемая величина",
                "work_day": WORK_DAY.isoformat(),
            },
        )
        assert created.status_code == 201

        day = await client.get(f"/api/v1/roles/day/{WORK_DAY.isoformat()}")
        payload = day.json()
        assert [act["title"] for act in payload["acts"]] == [
            "ADR-0020: роли как измеряемая величина"
        ]
        counts = {one["role_code"]: one["act_count"] for one in payload["roles"]}
        assert counts[ROLE_CODE_ARCHITECT] == 1
        assert counts[ROLE_CODE_TECHLEAD] == 0
        # Zero minutes and one act: the two measures are independent, which is
        # the whole reason both exist.
        assert payload["total_minutes"] == 0

    async def test_an_unknown_act_kind_is_refused(self, client: AsyncClient) -> None:
        """The vocabulary lives in the schema and is enforced there."""
        response = await client.post(
            "/api/v1/role-acts",
            json={
                "role_code": ROLE_CODE_CTO,
                "act_kind": "занимался делами",
                "title": "что-то",
            },
        )
        assert response.status_code == 422

    async def test_a_broken_regex_is_refused_when_the_rule_is_written(
        self, client: AsyncClient
    ) -> None:
        """A rule that could never fire is refused while its author is looking."""
        response = await client.post(
            "/api/v1/role-rules",
            json={
                "role_code": ROLE_CODE_ARCHITECT,
                "source": SOURCE_APP_USAGE,
                "matcher_kind": MATCHER_WINDOW_TITLE_REGEX,
                "pattern": "([unclosed",
            },
        )
        assert response.status_code == 422

    async def test_a_rule_is_written_and_read_back_in_applying_order(
        self, client: AsyncClient
    ) -> None:
        """Rules come back strongest first — the order they actually apply in."""
        weak = await client.post(
            "/api/v1/role-rules",
            json={
                "role_code": ROLE_CODE_TECHLEAD,
                "source": SOURCE_APP_USAGE,
                "matcher_kind": MATCHER_BUNDLE_ID,
                "pattern": "com.microsoft.VSCode",
                "priority": 100,
            },
        )
        strong = await client.post(
            "/api/v1/role-rules",
            json={
                "role_code": ROLE_CODE_ARCHITECT,
                "source": SOURCE_APP_USAGE,
                "matcher_kind": MATCHER_WINDOW_TITLE_REGEX,
                "pattern": "^ADR-",
                "priority": 10,
            },
        )
        assert weak.status_code == 201
        assert strong.status_code == 201

        listed = await client.get("/api/v1/role-rules")
        assert [one["priority"] for one in listed.json()] == [10, 100]
        assert listed.json()[0]["role_code"] == ROLE_CODE_ARCHITECT

    async def test_a_block_is_corrected_and_confirmed_by_hand(
        self, client: AsyncClient
    ) -> None:
        """The other half of «ручное поверх автоматики», over HTTP."""
        created = await client.post(
            "/api/v1/role-time-blocks",
            json={
                "role_code": ROLE_CODE_TECHLEAD,
                "minutes": 60,
                "work_day": WORK_DAY.isoformat(),
                "source": SOURCE_GIT,
                "external_ref": "9f1c2b7",
            },
        )
        block_id = created.json()["id"]

        patched = await client.patch(
            f"/api/v1/role-time-blocks/{block_id}",
            json={
                "role_code": ROLE_CODE_ARCHITECT,
                "minutes": 90,
                "confidence": CONFIDENCE_CONFIRMED,
            },
        )
        assert patched.status_code == 200
        assert patched.json()["role_code"] == ROLE_CODE_ARCHITECT
        assert patched.json()["confidence"] == CONFIDENCE_CONFIRMED

        # The importer comes back with its own answer and is ignored.
        again = await client.post(
            "/api/v1/role-time-blocks",
            json={
                "role_code": ROLE_CODE_TECHLEAD,
                "minutes": 60,
                "work_day": WORK_DAY.isoformat(),
                "source": SOURCE_GIT,
                "external_ref": "9f1c2b7",
            },
        )
        assert again.json()["role_code"] == ROLE_CODE_ARCHITECT
        assert again.json()["minutes"] == 90

    async def test_a_block_is_deleted(self, client: AsyncClient) -> None:
        """A record that never happened is deleted, not set to zero."""
        created = await client.post(
            "/api/v1/role-time-blocks",
            json={
                "role_code": ROLE_CODE_CTO,
                "minutes": 30,
                "work_day": WORK_DAY.isoformat(),
            },
        )
        removed = await client.delete(
            f"/api/v1/role-time-blocks/{created.json()['id']}"
        )
        assert removed.status_code == 204

        day = await client.get(f"/api/v1/roles/day/{WORK_DAY.isoformat()}")
        assert day.json()["total_minutes"] == 0
        assert day.json()["blocks"] == []
