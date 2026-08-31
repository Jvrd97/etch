# [review:need-review] PHASE-03/158
# summary: tests of the title privacy screen — a broken regex is refused on write with the reason and nothing is stored, reordering two rules changes which one wins on a title both of them match, a rule that fired on nothing reads «0», `titles_enabled=false` strips the title off every incoming interval while the application rows keep arriving, and the config the agent polls carries the rules so a rule saved in the web takes effect without a rebuild
"""
Tests of the title rules and of the kill switch.

The privacy policy is the one part of the theme a person edits regularly and in
a hurry, so the acceptance cases are about what happens when they get it wrong:
a pattern that does not compile, an order that puts `keep` above `drop`, a rule
with a typo that never fires.
"""

from collections.abc import AsyncGenerator
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.daytime import today_local
from app.crud import activity as activity_crud
from app.crud import role as role_crud
from app.models.activity import (
    TITLE_DROPPED,
    TITLE_FULL,
    ActivityInterval,
    ModeSchedule,
    TitleRule,
    TrackedApp,
)

AGENT_URL = "/api/v1/agent"
RULES_URL = f"{AGENT_URL}/title-rules"

VSCODE = "com.microsoft.VSCode"
ZONE = ZoneInfo(settings.APP_TIMEZONE)


@pytest.fixture(autouse=True)
async def seeded(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    """
    The settings row, the catalogue and the role directory.

    The settings row is seeded by the migration and `create_all` never sees a
    migration, so it is inserted here — the same reason `seed_roles` exists
    twice.
    """
    await activity_crud.seed_settings(db_session)
    db_session.add(ModeSchedule(weekday=today_local().isoweekday() % 7, kind="work"))
    db_session.add(TrackedApp(bundle_id=VSCODE, display_name="VS Code"))
    await role_crud.seed_roles(db_session)
    await db_session.commit()
    yield


def at(hour: int, minute: int = 0, day: date | None = None) -> datetime:
    on = day or today_local()
    return datetime(on.year, on.month, on.day, hour, minute, tzinfo=ZONE)


def rule_body(
    match_kind: str, pattern: str, action: str, **extra: Any
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "match_kind": match_kind,
        "pattern": pattern,
        "action": action,
    }
    body.update(extra)
    return body


async def add_rule(client: AsyncClient, body: dict[str, Any]) -> list[dict[str, Any]]:
    response = await client.post(RULES_URL, json=body)
    assert response.status_code == 201, response.text
    return list(response.json())


async def send_interval(
    client: AsyncClient,
    *,
    title: str | None = None,
    title_source: str = TITLE_FULL,
    start: datetime | None = None,
) -> None:
    started = start or at(10)
    response = await client.post(
        f"{AGENT_URL}/activity",
        json={
            "intervals": [
                {
                    "bundle_id": VSCODE,
                    "started_at": started.isoformat(),
                    "ended_at": (started + timedelta(hours=1)).isoformat(),
                    "local_date": started.date().isoformat(),
                    "title": title,
                    "title_source": title_source,
                }
            ]
        },
    )
    assert response.status_code == 201, response.text


# --- битый regex ------------------------------------------------------------


class TestPattern:
    async def test_an_unclosed_class_is_refused_and_nothing_is_stored(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """
        `[unclosed` не сохраняется: 422 с текстом ошибки, строки в таблице нет.

        Битый шаблон на маке молча ничего не матчит и оставляет заголовок
        правилу ниже — а ниже может стоять `keep`.
        """
        before = len(await activity_crud.list_title_rules(db_session))
        response = await client.post(
            RULES_URL, json=rule_body("title_regex", "[unclosed", "drop")
        )
        assert response.status_code == 422
        assert "[unclosed" in response.text
        after = len(await activity_crud.list_title_rules(db_session))
        assert after == before

    async def test_a_patch_that_breaks_the_pattern_is_refused_too(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Правка — тот же путь записи, и та же проверка на нём."""
        rules = await add_rule(client, rule_body("title_regex", "ADR", "keep"))
        rule_id = rules[0]["id"]
        response = await client.patch(
            f"{RULES_URL}/{rule_id}", json={"pattern": "(unclosed"}
        )
        assert response.status_code == 422
        stored = await activity_crud.get_title_rule(db_session, rule_id)
        assert stored is not None
        assert stored.pattern == "ADR"

    async def test_a_valid_regex_is_stored(self, client: AsyncClient) -> None:
        rules = await add_rule(client, rule_body("title_regex", r"ADR-\d+", "keep"))
        assert rules[-1]["pattern"] == r"ADR-\d+"


# --- порядок решает ---------------------------------------------------------


class TestOrder:
    async def test_reordering_changes_which_rule_wins(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """
        The acceptance case, on a concrete pair.

        `ADR-0020.md` matches both rules. With `keep` first the title is kept;
        with `drop` first it is dropped — and the only thing that changed is the
        order.
        """
        await add_rule(client, rule_body("title_regex", "ADR", "keep"))
        rules = await add_rule(client, rule_body("bundle_id", VSCODE, "drop"))
        keep_id = next(row["id"] for row in rules if row["action"] == "keep")
        drop_id = next(row["id"] for row in rules if row["action"] == "drop")

        stored = await activity_crud.list_title_rules(db_session)
        by_id = {rule.id: rule for rule in stored}
        title = "ADR-0020.md"
        first = next(
            rule for rule in stored if activity_crud.rule_matches(rule, VSCODE, title)
        )
        assert first.id == keep_id

        response = await client.put(
            f"{RULES_URL}/order", json={"order": [drop_id, keep_id]}
        )
        assert response.status_code == 200, response.text
        assert [row["id"] for row in response.json()] == [drop_id, keep_id]

        reordered = await activity_crud.list_title_rules(db_session)
        winner = next(
            rule
            for rule in reordered
            if activity_crud.rule_matches(rule, VSCODE, title)
        )
        assert winner.id == drop_id
        assert by_id[drop_id].action == "drop"

    async def test_an_unknown_id_in_the_order_is_a_404(
        self, client: AsyncClient
    ) -> None:
        rules = await add_rule(client, rule_body("bundle_id", VSCODE, "drop"))
        response = await client.put(
            f"{RULES_URL}/order", json={"order": [rules[0]["id"], 9999]}
        )
        assert response.status_code == 404

    async def test_a_new_rule_lands_at_the_end(self, client: AsyncClient) -> None:
        """
        В конец, а не в начало.

        Правило, добавленное в спешке, не должно молча перебить запрет, который
        стоял выше.
        """
        await add_rule(client, rule_body("bundle_id", VSCODE, "drop"))
        rules = await add_rule(client, rule_body("bundle_prefix", "com.apple", "mask"))
        assert rules[-1]["action"] == "mask"


# --- счётчик срабатываний ---------------------------------------------------


class TestHits:
    async def test_a_rule_that_never_fired_reads_zero(
        self, client: AsyncClient
    ) -> None:
        """
        Иначе правило с опечаткой выглядит ровно как работающее.
        """
        await send_interval(client, title="ADR-0020.md")
        rules = await add_rule(
            client, rule_body("bundle_id", "com.nobody.Uses", "drop")
        )
        assert rules[-1]["hits_7d"] == 0

    async def test_a_working_rule_counts_the_intervals_it_touches(
        self, client: AsyncClient
    ) -> None:
        await add_rule(client, rule_body("bundle_id", VSCODE, "mask"))
        await send_interval(client, start=at(10))
        await send_interval(client, start=at(12))

        response = await client.get(RULES_URL)
        assert response.status_code == 200
        assert response.json()[0]["hits_7d"] == 2

    async def test_only_the_first_matching_rule_counts_an_interval(
        self, client: AsyncClient
    ) -> None:
        """Считается ровно то, что происходит на маке: первое совпавшее выигрывает."""
        await add_rule(client, rule_body("bundle_id", VSCODE, "mask"))
        await add_rule(client, rule_body("bundle_prefix", "com.microsoft", "drop"))
        await send_interval(client)

        rows = (await client.get(RULES_URL)).json()
        assert [row["hits_7d"] for row in rows] == [1, 0]


# --- рубильник --------------------------------------------------------------


class TestKillSwitch:
    async def test_switching_titles_off_strips_them_from_new_intervals(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """
        The acceptance case: заголовков нет, а строки приложений идут.

        «Где прошёл день» и «что было в окне» — разные вопросы, и второй можно
        закрыть, не потеряв первый.
        """
        response = await client.put(
            f"{AGENT_URL}/settings", json={"titles_enabled": False}
        )
        assert response.status_code == 200, response.text
        assert response.json()["titles_enabled"] is False

        await send_interval(client, title="Договор аренды — Мюллер")

        stored = (await db_session.execute(select(ActivityInterval))).scalar_one()
        assert stored.title is None
        assert stored.title_source == TITLE_DROPPED

        day = await client.get(f"{AGENT_URL}/activity/{today_local().isoformat()}")
        assert day.json()["total_minutes"] == 60
        assert day.json()["apps"][0]["app_name"] == "VS Code"

    async def test_titles_that_already_left_are_not_deleted(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """
        Выключение — не чистка, и тикет об этом говорит прямо.

        Массовое `UPDATE ... SET title=NULL` делается руками по ADR; рубильник,
        который выглядел бы как «стереть всё», однажды был бы нажат вместо неё.
        """
        await send_interval(client, title="ADR-0020.md")
        await client.put(f"{AGENT_URL}/settings", json={"titles_enabled": False})

        stored = (await db_session.execute(select(ActivityInterval))).scalar_one()
        assert stored.title == "ADR-0020.md"

    async def test_the_switch_is_on_by_default(self, client: AsyncClient) -> None:
        """
        Политика и так default deny; второй запрет поверх неё означал бы, что
        разрешающие правила молча не работают.
        """
        response = await client.get(f"{AGENT_URL}/settings")
        assert response.json()["titles_enabled"] is True


# --- конфиг агента ----------------------------------------------------------


class TestConfig:
    async def test_the_config_carries_the_rules_and_the_switch(
        self, client: AsyncClient
    ) -> None:
        """
        The acceptance case: a rule saved in the web reaches the mac at the next
        poll — no rebuild of the `.app`, no restart.
        """
        await add_rule(client, rule_body("bundle_id", VSCODE, "drop", note="почта"))
        await client.put(f"{AGENT_URL}/settings", json={"sampling_seconds": 10})

        response = await client.get(f"{AGENT_URL}/config")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["titles_enabled"] is True
        assert body["sampling_seconds"] == 10
        assert body["day_mode"]["kind"] == "work"
        assert [rule["pattern"] for rule in body["title_rules"]] == [VSCODE]

    async def test_a_disabled_rule_still_travels_and_says_it_is_off(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """
        Выключенное правило остаётся строкой, а не исчезает.

        «Это правило я когда-то написал и выключил» — факт, который через месяц
        объясняет, почему заголовки этого приложения снова видно.
        """
        rules = await add_rule(client, rule_body("bundle_id", VSCODE, "drop"))
        await client.patch(f"{RULES_URL}/{rules[0]['id']}", json={"is_active": False})

        body = (await client.get(f"{AGENT_URL}/config")).json()
        assert body["title_rules"][0]["is_active"] is False
        assert (
            await db_session.execute(select(TitleRule))
        ).scalar_one().is_active is False

    async def test_a_deleted_rule_is_gone(self, client: AsyncClient) -> None:
        rules = await add_rule(client, rule_body("bundle_id", VSCODE, "drop"))
        response = await client.delete(f"{RULES_URL}/{rules[0]['id']}")
        assert response.status_code == 200
        assert response.json() == []
