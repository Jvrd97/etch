"""
Tests of the rules editor: publishing a version, and everything it must refuse.

The whole point of the feature is a negative one — the past does not move — so
most of what is checked here is what does *not* happen: verdicts computed before
a publication stay what they were, a row already in force cannot be edited
through any method the API answers, and a refusal leaves the table exactly as it
was found.
"""

# [review:need-review] PHASE-03/152
# summary: publishing a new canon — past verdicts unchanged, overlap refused by the database and reported in words, no edit handle at all, no gap left behind by a failed publication, the past-dated start rejected, and the history the screen reads
from datetime import date, time, timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.daytime import today_local
from app.crud import day as day_crud
from app.crud import day_rules as rules_crud
from app.main import app
from app.models.day import DayRuleSet
from app.schemas.day import DayRuleSetPublish

RULES_URL = "/api/v1/day-rule-sets"

# The ceiling the ticket publishes as the example change: seven hours.
SEVEN_HOURS_MIN = 7 * 60


def draft_payload(valid_from: date, **overrides: Any) -> dict[str, Any]:
    """A publishable version, by default the current canon moved to a new date."""
    payload: dict[str, Any] = {
        "valid_from": valid_from.isoformat(),
        "timezone": "Europe/Berlin",
        "day_start_hour": 4,
        "work_cap_min": 480,
        "work_hard_cap_min": 540,
        "work_stop_at": "16:00:00",
        "max_work_tasks": 4,
        "tasks_required_ratio": "1.00",
        "overtime_disqualifies": True,
        "workdays": [1, 2, 3, 4, 5],
        "nocode_days": [2, 4],
        "required_anchors": ["подъём", "спорт", "старт работы", "ревью", "отбой"],
        "note_md": "",
    }
    payload.update(overrides)
    return payload


def make_draft(valid_from: date, **overrides: Any) -> DayRuleSetPublish:
    """The same version as a validated draft, for the service-level tests."""
    return DayRuleSetPublish.model_validate(draft_payload(valid_from, **overrides))


def make_rule(
    valid_from: date, valid_to: date | None = None, *, work_cap_min: int = 480
) -> DayRuleSet:
    """A rule row built in memory, for states the API cannot produce itself."""
    return DayRuleSet(
        valid_from=valid_from,
        valid_to=valid_to,
        timezone="Europe/Berlin",
        day_start_hour=4,
        work_cap_min=work_cap_min,
        work_hard_cap_min=work_cap_min,
        work_stop_at=time(16, 0),
        max_work_tasks=4,
        tasks_required_ratio=Decimal("1.00"),
        overtime_disqualifies=True,
        workdays=[1, 2, 3, 4, 5],
        nocode_days=[2, 4],
        required_anchors=["подъём"],
        note_md="",
    )


# --- publishing does not move the past ---------------------------------------


async def test_publishing_a_lower_ceiling_leaves_past_verdicts_untouched(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """
    The acceptance case: a seven-hour ceiling from tomorrow changes no verdict of
    a day already lived. The days are re-read after the publication and compared
    with what they answered before it.
    """
    await day_crud.seed_rules(db_session)
    past = [date(2026, 8, 14), date(2026, 8, 18), today_local() - timedelta(days=1)]

    before = {}
    for on in past:
        response = await client.get(f"/api/v1/day/{on.isoformat()}")
        assert response.status_code == 200
        before[on] = response.json()["summary"]

    published = await client.post(
        RULES_URL,
        json=draft_payload(
            today_local() + timedelta(days=1),
            work_cap_min=SEVEN_HOURS_MIN,
            work_hard_cap_min=SEVEN_HOURS_MIN,
        ),
    )
    assert published.status_code == 201, published.text

    for on in past:
        response = await client.get(f"/api/v1/day/{on.isoformat()}")
        assert response.json()["summary"] == before[on], on
        # And the numbers the day is read against are the old ones, which is
        # why the verdict could not have moved.
        assert response.json()["rule"]["work_cap_min"] != SEVEN_HOURS_MIN


async def test_the_published_version_takes_over_from_its_start_date(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await day_crud.seed_rules(db_session)
    starts = today_local() + timedelta(days=2)
    assert (
        await client.post(
            RULES_URL, json=draft_payload(starts, work_cap_min=SEVEN_HOURS_MIN)
        )
    ).status_code == 201

    on_the_day = await client.get(f"/api/v1/day/{starts.isoformat()}")
    day_before = await client.get(
        f"/api/v1/day/{(starts - timedelta(days=1)).isoformat()}"
    )
    assert on_the_day.json()["rule"]["work_cap_min"] == SEVEN_HOURS_MIN
    assert day_before.json()["rule"]["work_cap_min"] == 480


async def test_the_two_versions_meet_without_a_gap(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """`valid_to` of the closed version is `valid_from` of the new one."""
    await day_crud.seed_rules(db_session)
    starts = today_local() + timedelta(days=1)
    await client.post(RULES_URL, json=draft_payload(starts))

    rules = await day_crud.list_rules(db_session)
    bounds = [(rule.valid_from, rule.valid_to) for rule in rules]
    for (_, ends), (begins, _) in zip(bounds, bounds[1:]):
        assert ends == begins
    assert bounds[-1][1] is None


# --- what publishing refuses --------------------------------------------------


@pytest.mark.parametrize("days_back", [0, 1, 30])
async def test_a_start_date_that_is_not_in_the_future_is_refused(
    client: AsyncClient, db_session: AsyncSession, days_back: int
) -> None:
    """
    Today counts as the past here: today is being lived, may already be closed,
    and its verdict is computed by the rule in force now.
    """
    await day_crud.seed_rules(db_session)
    response = await client.post(
        RULES_URL, json=draft_payload(today_local() - timedelta(days=days_back))
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, str)
    assert "вердикты уже считаются" in detail
    assert rules_crud.earliest_valid_from(today_local()).isoformat() in detail


async def test_a_refused_publication_changes_nothing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await day_crud.seed_rules(db_session)
    before = [
        (rule.valid_from, rule.valid_to)
        for rule in await day_crud.list_rules(db_session)
    ]
    await client.post(RULES_URL, json=draft_payload(today_local()))
    after = [
        (rule.valid_from, rule.valid_to)
        for rule in await day_crud.list_rules(db_session)
    ]
    assert after == before


async def test_an_overlapping_period_is_refused_by_the_database_in_words(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """
    A version already published for a later date is not sandwiched or edited:
    the insert reaches the exclusion constraint, and what comes back is a
    sentence rather than `ExclusionViolation`.
    """
    later = today_local() + timedelta(days=20)
    db_session.add(make_rule(date(2020, 1, 1), later))
    db_session.add(make_rule(later, None))
    await db_session.flush()

    response = await client.post(
        RULES_URL, json=draft_payload(today_local() + timedelta(days=10))
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "перекрывает" in detail
    assert "ExclusionViolation" not in detail
    assert "psycopg" not in detail and "asyncpg" not in detail


async def test_a_failed_publication_leaves_no_gap_between_versions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """
    The one that has to be a savepoint: closing the previous version happens,
    the insert then fails, and the previous version must come back with the
    `valid_to` it had — otherwise the canon has a hole no rule covers.
    """
    later = today_local() + timedelta(days=20)
    db_session.add(make_rule(date(2020, 1, 1), later))
    db_session.add(make_rule(later, None))
    await db_session.flush()

    response = await client.post(
        RULES_URL, json=draft_payload(today_local() + timedelta(days=10))
    )
    assert response.status_code == 409

    rules = await day_crud.list_rules(db_session)
    assert [(rule.valid_from, rule.valid_to) for rule in rules] == [
        (date(2020, 1, 1), later),
        (later, None),
    ]
    # No hole: every date between the first version and the last is covered.
    covered = date(2020, 1, 1)
    for rule in rules:
        assert rule.valid_from == covered
        covered = rule.valid_to if rule.valid_to is not None else covered


async def test_a_version_starting_where_another_already_starts_is_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Re-publishing over a version somebody already published is an edit."""
    starts = today_local() + timedelta(days=3)
    await day_crud.seed_rules(db_session)
    assert (await client.post(RULES_URL, json=draft_payload(starts))).status_code == 201

    again = await client.post(
        RULES_URL, json=draft_payload(starts, work_cap_min=SEVEN_HOURS_MIN)
    )
    assert again.status_code == 409
    assert "перекрывает" in again.json()["detail"]


# --- editing a row in force is not a thing the API can do ---------------------


def test_the_router_answers_no_method_that_edits_a_rule() -> None:
    """
    Mechanically, not by review: any PUT, PATCH or DELETE under this prefix
    would be a way to rewrite a row that has already judged days, which is the
    single thing the whole versioned table exists to prevent.
    """
    forbidden = {"PUT", "PATCH", "DELETE"}
    # `app.routes` is a list of the base `BaseRoute`, which carries neither
    # `path` nor `methods`; read through `getattr` rather than narrowing the
    # union, so that a route class without them is skipped instead of crashing
    # the guard the whole property rests on.
    offenders = [
        (path, sorted(methods & forbidden))
        for path, methods in (
            (getattr(route, "path", ""), getattr(route, "methods", set()))
            for route in app.routes
        )
        if path.startswith(RULES_URL) and methods & forbidden
    ]
    assert offenders == []


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
async def test_editing_the_current_rule_is_refused_by_the_api(
    client: AsyncClient, db_session: AsyncSession, method: str
) -> None:
    await day_crud.seed_rules(db_session)
    current = await rules_crud.current_rule(db_session)
    for url in (f"{RULES_URL}/current", f"{RULES_URL}/{current.id}", RULES_URL):
        response = await client.request(method, url, json={"work_cap_min": 420})
        assert response.status_code in (404, 405), (method, url)


# --- what the screen reads ----------------------------------------------------


async def test_history_answers_every_version_and_the_earliest_date(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await day_crud.seed_rules(db_session)
    response = await client.get(RULES_URL)
    assert response.status_code == 200
    body = response.json()

    assert [rule["valid_from"] for rule in body["rules"]] == [
        "2020-01-01",
        "2026-08-17",
    ]
    assert body["today"] == today_local().isoformat()
    assert (
        body["earliest_valid_from"] == (today_local() + timedelta(days=1)).isoformat()
    )
    assert body["current_id"] == body["rules"][-1]["id"]


async def test_history_carries_the_whole_rule_not_just_its_dates(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The screen shows the canon in full — edges, ceilings, anchors."""
    await day_crud.seed_rules(db_session)
    current = (await client.get(RULES_URL)).json()["rules"][-1]
    assert current["work_cap_min"] == 480
    assert current["work_hard_cap_min"] == 540
    assert current["work_stop_at"] == "16:00:00"
    assert current["day_start_hour"] == 4
    assert current["timezone"] == "Europe/Berlin"
    assert current["required_anchors"][0] == "подъём"
    assert current["nocode_days"] == [2, 4]


async def test_history_of_an_empty_table_is_empty_rather_than_an_error(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    body = (await client.get(RULES_URL)).json()
    assert body["rules"] == []
    assert body["current_id"] is None


async def test_current_answers_the_rule_in_force(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await day_crud.seed_rules(db_session)
    body = (await client.get(f"{RULES_URL}/current")).json()
    assert body["valid_from"] == "2026-08-17"
    assert body["valid_to"] is None


async def test_current_of_an_empty_table_says_what_is_missing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    response = await client.get(f"{RULES_URL}/current")
    assert response.status_code == 404
    assert "миграция" in response.json()["detail"]


# --- the draft is validated before it can become a version --------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"timezone": "Europe/Berlim"},
        {"day_start_hour": 24},
        {"work_cap_min": 0},
        {"work_hard_cap_min": 400},
        {"max_work_tasks": 0},
        {"tasks_required_ratio": "1.50"},
        {"workdays": [0, 1, 2]},
        {"nocode_days": [2, 2]},
        {"required_anchors": ["подъём", "подъём"]},
        {"required_anchors": [" "]},
        {"valid_to": "2027-01-01"},
        {"id": 7},
    ],
)
async def test_a_malformed_version_never_reaches_the_table(
    client: AsyncClient, db_session: AsyncSession, overrides: dict[str, Any]
) -> None:
    await day_crud.seed_rules(db_session)
    before = len(await day_crud.list_rules(db_session))
    response = await client.post(
        RULES_URL,
        json=draft_payload(today_local() + timedelta(days=1), **overrides),
    )
    assert response.status_code == 422, overrides
    assert len(await day_crud.list_rules(db_session)) == before


async def test_the_published_row_keeps_an_open_end(
    db_session: AsyncSession,
) -> None:
    """`valid_to` is the service's to write, never the caller's."""
    await day_crud.seed_rules(db_session)
    created = await rules_crud.publish_rule_set(
        db_session, make_draft(today_local() + timedelta(days=1))
    )
    assert created.valid_to is None
