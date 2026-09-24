# [review:need-review] PHASE-03/180
# summary: one human-confirmation predicate protects the same persisted block through both role-classification routes and accepts both stored-confidence and sample-boolean representations
"""One shared rule protects human-confirmed role data from reclassification."""

from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
import re
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import activity as activity_crud
from app.crud import role as role_crud
from app.models.activity import (
    TITLE_DROPPED,
    ActivityInterval,
    ModeSchedule,
    TrackedApp,
)
from app.models.role import (
    CONFIDENCE_CONFIRMED,
    MATCHER_BUNDLE_ID,
    ROLE_CODE_ARCHITECT,
    ROLE_CODE_TECHLEAD,
    SOURCE_APP_USAGE,
    RoleTimeBlock,
)
from app.roles import rules_editor
from app.roles.samples import (
    HistoricalSample,
    historical_samples,
    is_confirmed_by_person,
)

WORK_DAY = date(2026, 8, 31)
ROLES_URL = "/api/v1/roles"
BERLIN = ZoneInfo("Europe/Berlin")


@pytest.fixture(autouse=True)
async def role_directory(db_session: AsyncSession) -> None:
    await role_crud.seed_roles(db_session)
    await activity_crud.seed_settings(db_session)
    app = TrackedApp(bundle_id="com.example.editor", display_name="Editor")
    db_session.add(app)
    db_session.add(ModeSchedule(weekday=1, kind="work", nocode=False))
    await db_session.flush()
    db_session.info["confirmed_guard_app_id"] = app.id
    await db_session.commit()


async def role_id(db: AsyncSession, code: str) -> int:
    role = await role_crud.get_role_by_code(db, code)
    assert role is not None
    return role.id


async def seed_confirmed_interval(
    db: AsyncSession, confidence: str = CONFIDENCE_CONFIRMED
) -> RoleTimeBlock:
    app_id = int(db.info["confirmed_guard_app_id"])
    interval = ActivityInterval(
        app_id=app_id,
        started_at=datetime(2026, 8, 31, 10, tzinfo=BERLIN),
        ended_at=datetime(2026, 8, 31, 11, tzinfo=BERLIN),
        local_date=WORK_DAY,
        title_source=TITLE_DROPPED,
    )
    db.add(interval)
    await db.flush()
    outcome = await role_crud.write_time_block(
        db,
        role_crud.TimeBlockDraft(
            work_day=WORK_DAY,
            role_id=await role_id(db, ROLE_CODE_ARCHITECT),
            minutes=60,
            source=SOURCE_APP_USAGE,
            confidence=confidence,
            external_ref=f"{interval.id}:{WORK_DAY.isoformat()}",
            note="com.example.editor",
        ),
    )
    rule = await role_crud.create_rule(
        db,
        role_id=await role_id(db, ROLE_CODE_TECHLEAD),
        source=SOURCE_APP_USAGE,
        matcher_kind=MATCHER_BUNDLE_ID,
        pattern="com.example.editor",
        priority=100,
    )
    outcome.row.rule_id = rule.id
    await db.commit()
    return outcome.row


@pytest.mark.asyncio
async def test_both_classification_routes_preserve_the_same_confirmed_row(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The two public promises protect the same seeded row and leave its data intact."""
    original = await seed_confirmed_interval(db_session)
    expected = (original.role_id, original.minutes, original.confidence, original.note)

    classify_response = await client.post(
        f"{ROLES_URL}/classify",
        json={"date_from": WORK_DAY.isoformat(), "date_to": WORK_DAY.isoformat()},
    )
    assert classify_response.status_code == 200, classify_response.text
    assert classify_response.json()["days"][0]["kept_confirmed"] == 1

    reclassify_response = await client.post(
        f"{ROLES_URL}/reclassify",
        json={"date_from": WORK_DAY.isoformat(), "date_to": WORK_DAY.isoformat()},
    )
    assert reclassify_response.status_code == 200, reclassify_response.text
    assert reclassify_response.json()["protected"] == 1

    result = await db_session.execute(
        select(RoleTimeBlock).where(RoleTimeBlock.id == original.id)
    )
    row = result.scalar_one()
    assert (row.role_id, row.minutes, row.confidence, row.note) == expected


@pytest.mark.asyncio
async def test_reclassify_protects_sample_with_confirmed_boolean(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The route honors `HistoricalSample.confirmed` even when storage says auto."""
    original = await seed_confirmed_interval(db_session, confidence="auto")
    samples = await historical_samples(db_session, WORK_DAY, WORK_DAY)
    assert len(samples) == 1
    assert samples[0].confirmed is False
    confirmed_sample = replace(samples[0], confirmed=True)

    async def load_confirmed_sample(
        db: AsyncSession, date_from: date, date_to: date
    ) -> list[HistoricalSample]:
        assert date_from == WORK_DAY
        assert date_to == WORK_DAY
        return [confirmed_sample]

    monkeypatch.setattr(rules_editor, "historical_samples", load_confirmed_sample)
    response = await client.post(
        f"{ROLES_URL}/reclassify",
        json={"date_from": WORK_DAY.isoformat(), "date_to": WORK_DAY.isoformat()},
    )

    assert response.status_code == 200, response.text
    assert response.json()["protected"] == 1
    await db_session.refresh(original)
    assert original.role_id == await role_id(db_session, ROLE_CODE_ARCHITECT)
    assert original.confidence == "auto"


def test_shared_predicate_accepts_both_confirmation_representations() -> None:
    assert is_confirmed_by_person(confidence=CONFIDENCE_CONFIRMED)
    assert is_confirmed_by_person(confidence="auto", confirmed=True)
    assert not is_confirmed_by_person(confidence="auto")


def test_role_services_do_not_compare_confirmation_fields_directly() -> None:
    backend_root = Path(__file__).parents[1]
    roles_root = backend_root / "app" / "roles"
    direct_comparison = re.compile(
        r"(?:\.confidence|\bconfidence|\bconfirmed)\s*==\s*"
        r"(?:CONFIDENCE_CONFIRMED|['\"]confirmed['\"]|True)"
    )
    predicate_source = (roles_root / "samples.py").read_text(encoding="utf-8")
    assert predicate_source.count("confidence == CONFIDENCE_CONFIRMED") == 1
    offenders = [
        path.relative_to(backend_root).as_posix()
        for path in roles_root.rglob("*.py")
        if path.name != "samples.py"
        and direct_comparison.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
