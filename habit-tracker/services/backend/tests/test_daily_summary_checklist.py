"""
Tests for the checklist half of the day plan: a retelling that ticks boxes.

The whole point of this slice is what the plan *cannot* say. `PUT
/entries/checklist` takes a full map, so a plan allowed to fill that map in
would silently untick everything the retelling failed to mention — and silence
is not "не сделал", it is "не сказал". These tests pin the two halves of that:
the schema has no way to express an untick, and the apply merges onto whatever
the day already holds instead of replacing it.
"""

# [review:need-review] PHASE-01/75-daily-summary-checklist
# summary: unit tests for the check op schema (tick-only), its semantic validation, the pure merge onto the day's current state, and API tests for applying ticks inside the day's transaction — both rollback directions, the stray second entry of a date, and the replay guard on a pre-filled metric field
import json
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import category as category_crud
from app.crud import entry as entry_crud
from app.crud.daily_summary import merge_checklist_marks, validate_check_ops
from app.llm.daily_summary import (
    DailySummaryPlanError,
    build_checklist_catalog,
    parse_plan,
)
from app.models import Entry
from app.schemas.daily_summary import CheckOp

ENTRY_DATE = "2026-07-30"
ENTRY_DAY = date(2026, 7, 30)


async def _make_checklist_category(
    client: AsyncClient, db_session: AsyncSession, name: str = "Витамины"
) -> tuple[int, int, int]:
    """Create a two-box checklist category; return (category_id, b12_id, d3_id)."""
    response = await client.post(
        "/api/v1/categories",
        json={
            "name": name,
            "display_mode": "checklist",
            "fields": [
                {"name": "B12", "field_type": "boolean", "order": 1},
                {"name": "D3", "field_type": "boolean", "order": 2},
            ],
        },
    )
    assert response.status_code == 201
    category = await category_crud.get_category(db_session, response.json()["id"])
    assert category is not None
    fields = {f.name: f.id for f in category.fields}
    return category.id, fields["B12"], fields["D3"]


async def _make_form_category(
    client: AsyncClient, db_session: AsyncSession, name: str = "Спорт"
) -> tuple[int, int]:
    """Create a one-number form category; return (category_id, field_id)."""
    response = await client.post(
        "/api/v1/categories",
        json={
            "name": name,
            "fields": [{"name": "Отжимания", "field_type": "number", "order": 1}],
        },
    )
    assert response.status_code == 201
    category = await category_crud.get_category(db_session, response.json()["id"])
    assert category is not None
    return category.id, category.fields[0].id


def _check_payload(category_id: int, field_id: int) -> dict[str, object]:
    return {
        "op": "check",
        "category_id": category_id,
        "field_id": field_id,
        "source_text": "выпил витамин B12",
    }


async def _checklist_state(
    db_session: AsyncSession, category_id: int
) -> dict[int, bool]:
    return await entry_crud.get_checklist_state(db_session, category_id, ENTRY_DAY)


# --------------------------------------------------------------------------- #
# The schema: only up
# --------------------------------------------------------------------------- #


class TestCheckOpSchema:
    def test_parses_a_tick(self) -> None:
        plan = parse_plan(
            json.dumps(
                {"metrics": [], "unresolved": [], "checklist": [_check_payload(4, 9)]}
            )
        )
        assert len(plan.checklist) == 1
        assert plan.checklist[0].category_id == 4
        assert plan.checklist[0].field_id == 9

    def test_unticking_is_not_expressible(self) -> None:
        """There is no `value` on a check op, so `false` has nowhere to live."""
        payload = _check_payload(4, 9) | {"value": False}
        with pytest.raises(DailySummaryPlanError):
            parse_plan(
                json.dumps({"metrics": [], "unresolved": [], "checklist": [payload]})
            )

    def test_check_op_has_no_value_field_at_all(self) -> None:
        assert "value" not in CheckOp.model_fields

    def test_plan_without_checklist_parses_with_an_empty_one(self) -> None:
        plan = parse_plan(json.dumps({"metrics": [], "unresolved": []}))
        assert plan.checklist == []


# --------------------------------------------------------------------------- #
# Semantic validation
# --------------------------------------------------------------------------- #


def _op(category_id: int, field_id: int) -> CheckOp:
    return CheckOp(
        category_id=category_id, field_id=field_id, source_text="выпил витамин B12"
    )


@pytest.mark.asyncio
class TestValidateCheckOps:
    async def test_boolean_field_of_a_checklist_category_passes(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        category_id, b12_id, _ = await _make_checklist_category(client, db_session)
        categories = await category_crud.get_categories(db_session, limit=None)

        assert validate_check_ops([_op(category_id, b12_id)], categories) == []

    async def test_unknown_category_id_is_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _make_checklist_category(client, db_session)
        categories = await category_crud.get_categories(db_session, limit=None)

        errors = validate_check_ops([_op(9999, 1)], categories)

        assert errors and "category_id" in errors[0]

    async def test_non_boolean_field_is_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A number field is not a checkbox, whatever the category's mode."""
        category_id, _, _ = await _make_checklist_category(client, db_session)
        response = await client.post(
            f"/api/v1/categories/{category_id}/fields",
            json={"name": "Доза", "field_type": "number", "order": 3},
        )
        assert response.status_code == 201
        number_field_id = response.json()["id"]
        categories = await category_crud.get_categories(db_session, limit=None)

        errors = validate_check_ops([_op(category_id, number_field_id)], categories)

        assert errors and str(number_field_id) in errors[0]

    async def test_field_of_a_form_category_is_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """display_mode is part of the contract of PUT /entries/checklist."""
        form_id, _ = await _make_form_category(client, db_session)
        response = await client.post(
            f"/api/v1/categories/{form_id}/fields",
            json={"name": "Размялся", "field_type": "boolean", "order": 2},
        )
        assert response.status_code == 201
        boolean_field_id = response.json()["id"]
        categories = await category_crud.get_categories(db_session, limit=None)

        errors = validate_check_ops([_op(form_id, boolean_field_id)], categories)

        assert errors and "checklist" in errors[0]

    async def test_field_from_another_category_is_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        first_id, _, _ = await _make_checklist_category(client, db_session, "Витамины")
        _, other_b12, _ = await _make_checklist_category(client, db_session, "Привычки")
        categories = await category_crud.get_categories(db_session, limit=None)

        errors = validate_check_ops([_op(first_id, other_b12)], categories)

        assert errors and "does not belong" in errors[0]


@pytest.mark.asyncio
class TestChecklistCatalog:
    async def test_catalog_lists_boolean_fields_of_checklist_categories(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        category_id, b12_id, _ = await _make_checklist_category(client, db_session)
        categories = await category_crud.get_categories(db_session, limit=None)

        catalog = build_checklist_catalog(categories)

        assert f"category_id={category_id}" in catalog
        assert f"field_id={b12_id}" in catalog

    async def test_form_categories_are_left_out(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        form_id, _ = await _make_form_category(client, db_session)
        categories = await category_crud.get_categories(db_session, limit=None)

        assert f"category_id={form_id}" not in build_checklist_catalog(categories)


# --------------------------------------------------------------------------- #
# The merge — a pure function, because this is where the data loss would be
# --------------------------------------------------------------------------- #


class TestMergeChecklistMarks:
    def test_mentioned_box_is_ticked(self) -> None:
        assert merge_checklist_marks({}, [7]) == {7: True}

    def test_unmentioned_box_keeps_its_value(self) -> None:
        """Silence is "не сказал", not "не сделал"."""
        assert merge_checklist_marks({7: True, 8: False}, [9]) == {
            7: True,
            8: False,
            9: True,
        }

    def test_a_box_ticked_by_hand_is_never_dropped(self) -> None:
        assert merge_checklist_marks({7: True}, [8])[7] is True

    def test_no_marks_changes_nothing(self) -> None:
        current = {7: True, 8: False}
        assert merge_checklist_marks(current, []) == current

    def test_current_state_is_not_mutated(self) -> None:
        current = {7: True}
        merge_checklist_marks(current, [8])
        assert current == {7: True}


# --------------------------------------------------------------------------- #
# The apply
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
class TestApplyChecklist:
    async def test_mentioned_item_is_ticked_for_the_date(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        category_id, b12_id, _ = await _make_checklist_category(client, db_session)

        response = await client.post(
            "/api/v1/daily-summary/apply",
            json={
                "entry_date": ENTRY_DATE,
                "metrics": [],
                "checklist": [_check_payload(category_id, b12_id)],
            },
        )

        assert response.status_code == 201
        assert await _checklist_state(db_session, category_id) == {b12_id: True}

    async def test_box_ticked_by_hand_survives_a_retelling_that_omits_it(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        category_id, b12_id, d3_id = await _make_checklist_category(client, db_session)
        morning = await client.put(
            "/api/v1/entries/checklist",
            json={
                "category_id": category_id,
                "entry_date": ENTRY_DATE,
                "values": {str(d3_id): True},
            },
        )
        assert morning.status_code == 200

        response = await client.post(
            "/api/v1/daily-summary/apply",
            json={
                "entry_date": ENTRY_DATE,
                "metrics": [],
                "checklist": [_check_payload(category_id, b12_id)],
            },
        )

        assert response.status_code == 201
        assert await _checklist_state(db_session, category_id) == {
            b12_id: True,
            d3_id: True,
        }

    @pytest.mark.parametrize("stored", ["1", "yes", "True"])
    async def test_a_box_stored_in_another_truthy_spelling_survives(
        self, client: AsyncClient, db_session: AsyncSession, stored: str
    ) -> None:
        """A tick is a tick however it was spelled — `is_true_value` says so.

        `upsert_checklist_values` writes "true", but it is not the only writer:
        `POST /entries` takes the string it is handed, and `crud/streak.py` and
        `crud/table.py` have long read {"true", "1", "yes"} case-insensitively.
        Reading the day with a strict `== "true"` makes such a box look empty,
        and the merge then writes "false" over it — the one thing this slice
        exists to make impossible.
        """
        category_id, b12_id, d3_id = await _make_checklist_category(client, db_session)
        logged = await client.post(
            "/api/v1/entries",
            json={
                "category_id": category_id,
                "entry_date": ENTRY_DATE,
                "values": [{"field_id": d3_id, "value": stored}],
            },
        )
        assert logged.status_code == 201

        response = await client.post(
            "/api/v1/daily-summary/apply",
            json={
                "entry_date": ENTRY_DATE,
                "metrics": [],
                "checklist": [_check_payload(category_id, b12_id)],
            },
        )

        assert response.status_code == 201
        assert await _checklist_state(db_session, category_id) == {
            b12_id: True,
            d3_id: True,
        }

    async def test_plan_without_a_checklist_leaves_the_day_alone(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        category_id, b12_id, d3_id = await _make_checklist_category(client, db_session)
        sport_id, pushups_id = await _make_form_category(client, db_session)
        await client.put(
            "/api/v1/entries/checklist",
            json={
                "category_id": category_id,
                "entry_date": ENTRY_DATE,
                "values": {str(b12_id): True, str(d3_id): False},
            },
        )

        response = await client.post(
            "/api/v1/daily-summary/apply",
            json={
                "entry_date": ENTRY_DATE,
                "metrics": [
                    {
                        "op": "log_metric",
                        "category_id": sport_id,
                        "field_id": pushups_id,
                        "value": 30,
                        "source_text": "отжался 30 раз",
                    }
                ],
            },
        )

        assert response.status_code == 201
        assert await _checklist_state(db_session, category_id) == {
            b12_id: True,
            d3_id: False,
        }

    async def test_non_boolean_field_is_rejected_with_422(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        category_id, _, _ = await _make_checklist_category(client, db_session)
        created = await client.post(
            f"/api/v1/categories/{category_id}/fields",
            json={"name": "Доза", "field_type": "number", "order": 3},
        )
        assert created.status_code == 201

        response = await client.post(
            "/api/v1/daily-summary/apply",
            json={
                "entry_date": ENTRY_DATE,
                "metrics": [],
                "checklist": [_check_payload(category_id, created.json()["id"])],
            },
        )

        assert response.status_code == 422

    async def test_field_of_a_form_category_is_rejected_with_422(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        form_id, _ = await _make_form_category(client, db_session)
        created = await client.post(
            f"/api/v1/categories/{form_id}/fields",
            json={"name": "Размялся", "field_type": "boolean", "order": 2},
        )
        assert created.status_code == 201

        response = await client.post(
            "/api/v1/daily-summary/apply",
            json={
                "entry_date": ENTRY_DATE,
                "metrics": [],
                "checklist": [_check_payload(form_id, created.json()["id"])],
            },
        )

        assert response.status_code == 422

    async def test_a_rejected_metric_takes_the_ticks_back_out(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """One transaction: the day is written whole or not at all."""
        category_id, b12_id, _ = await _make_checklist_category(client, db_session)

        response = await client.post(
            "/api/v1/daily-summary/apply",
            json={
                "entry_date": ENTRY_DATE,
                "metrics": [
                    {
                        "op": "log_metric",
                        "category_id": 999999,
                        "field_id": 999999,
                        "value": 30,
                        "source_text": "отжался 30 раз",
                    }
                ],
                "checklist": [_check_payload(category_id, b12_id)],
            },
        )

        assert response.status_code == 400
        assert await _checklist_state(db_session, category_id) == {}

    async def test_a_rejected_tick_takes_a_written_metric_back_out(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The other direction of the same transaction, and a reachable one.

        The metrics loop runs before `_checks_by_category`, so by the time a bad
        tick is refused the numbers are already flushed. A day left holding the
        push-ups of a plan that was rejected is exactly the half-written state
        the apply promises cannot happen.
        """
        sport_id, pushups_id = await _make_form_category(client, db_session)
        form_id, _ = await _make_form_category(client, db_session, "Утро")
        created = await client.post(
            f"/api/v1/categories/{form_id}/fields",
            json={"name": "Размялся", "field_type": "boolean", "order": 2},
        )
        assert created.status_code == 201

        response = await client.post(
            "/api/v1/daily-summary/apply",
            json={
                "entry_date": ENTRY_DATE,
                "metrics": [
                    {
                        "op": "log_metric",
                        "category_id": sport_id,
                        "field_id": pushups_id,
                        "value": 30,
                        "source_text": "отжался 30 раз",
                    }
                ],
                # A boolean field of a *form* category: valid metric first,
                # refused tick second.
                "checklist": [_check_payload(form_id, created.json()["id"])],
            },
        )

        assert response.status_code == 422
        entries = (
            (
                await db_session.execute(
                    select(Entry).where(Entry.category_id == sport_id)
                )
            )
            .scalars()
            .all()
        )
        assert entries == []

    async def test_a_stray_entry_cannot_untick_the_day(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The day's ticks come from the day's entry, not from every row of the date.

        A second entry for the same (category, date) is possible — the invariant
        is ours, not the database's, and the form endpoint will happily make one.
        When it carries "false" for a box the day's own entry has ticked, a read
        that merged both rows could take the "false" and the apply would write it
        back, unticking a box nobody mentioned.
        """
        category_id, b12_id, d3_id = await _make_checklist_category(client, db_session)
        morning = await client.put(
            "/api/v1/entries/checklist",
            json={
                "category_id": category_id,
                "entry_date": ENTRY_DATE,
                "values": {str(b12_id): True},
            },
        )
        assert morning.status_code == 200
        canonical_id = morning.json()["id"]

        stray = await client.post(
            "/api/v1/entries",
            json={
                "category_id": category_id,
                "entry_date": ENTRY_DATE,
                "values": [{"field_id": b12_id, "value": "false"}],
            },
        )
        assert stray.status_code == 201
        # The tick stands in the *smaller* id — the row every checklist write
        # resolves to.
        assert canonical_id < stray.json()["id"]

        response = await client.post(
            "/api/v1/daily-summary/apply",
            json={
                "entry_date": ENTRY_DATE,
                "checklist": [_check_payload(category_id, d3_id)],
            },
        )

        assert response.status_code == 201
        assert await _checklist_state(db_session, category_id) == {
            b12_id: True,
            d3_id: True,
        }

    async def test_a_key_reused_with_a_metric_into_a_prefilled_field_is_a_conflict(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A number already in the day's entry is not proof that this key wrote it.

        The apply reuses a checklist category's existing entry, so the entry
        holds whatever was typed into it before. If the replay guard read the
        entry's contents, a key that wrote only ticks would look like it had
        written the number too — and the added metric would be answered 200 and
        lost for good, since the key can never write it afterwards.
        """
        category_id, b12_id, _ = await _make_checklist_category(client, db_session)
        created = await client.post(
            f"/api/v1/categories/{category_id}/fields",
            json={"name": "Доза", "field_type": "number", "order": 3},
        )
        assert created.status_code == 201
        dose_id = created.json()["id"]

        # By hand, before any apply: the day's entry already carries the number.
        by_hand = await client.post(
            "/api/v1/entries",
            json={
                "category_id": category_id,
                "entry_date": ENTRY_DATE,
                "values": [{"field_id": dose_id, "value": "500"}],
            },
        )
        assert by_hand.status_code == 201
        entry_id = by_hand.json()["id"]

        headers = {"Idempotency-Key": "day-key-prefilled-metric"}
        first = await client.post(
            "/api/v1/daily-summary/apply",
            json={
                "entry_date": ENTRY_DATE,
                "checklist": [_check_payload(category_id, b12_id)],
            },
            headers=headers,
        )
        assert first.status_code == 201
        assert first.json()["entry_ids"] == [entry_id]

        second = await client.post(
            "/api/v1/daily-summary/apply",
            json={
                "entry_date": ENTRY_DATE,
                "metrics": [
                    {
                        "op": "log_metric",
                        "category_id": category_id,
                        "field_id": dose_id,
                        "value": 1000,
                        "source_text": "выпил 1000 единиц",
                    }
                ],
                "checklist": [_check_payload(category_id, b12_id)],
            },
            headers=headers,
        )

        assert second.status_code == 409
        assert str(category_id) in second.json()["detail"]
        # Nothing was written: the hand-typed number stands untouched.
        values = await entry_crud.get_entry(db_session, entry_id)
        assert values is not None
        assert [v.value for v in values.values if v.field_id == dose_id] == ["500"]

    async def test_a_checklist_only_apply_is_not_an_empty_request(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        category_id, b12_id, _ = await _make_checklist_category(client, db_session)

        response = await client.post(
            "/api/v1/daily-summary/apply",
            json={
                "entry_date": ENTRY_DATE,
                "checklist": [_check_payload(category_id, b12_id)],
            },
        )

        assert response.status_code == 201

    async def test_replay_under_the_same_key_writes_nothing_new(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The identical repeat: same key, same ticks — the second click is a no-op."""
        category_id, b12_id, d3_id = await _make_checklist_category(client, db_session)
        payload = {
            "entry_date": ENTRY_DATE,
            "checklist": [_check_payload(category_id, b12_id)],
        }
        headers = {"Idempotency-Key": "day-key-1"}

        first = await client.post(
            "/api/v1/daily-summary/apply", json=payload, headers=headers
        )
        assert first.status_code == 201

        # Between the two clicks the user ticks D3 by hand on Today. A replay
        # that re-ran the apply would be harmless here, but one that re-read and
        # rewrote a stale map would drop it.
        await client.put(
            "/api/v1/entries/checklist",
            json={
                "category_id": category_id,
                "entry_date": ENTRY_DATE,
                "values": {str(d3_id): True},
            },
        )

        second = await client.post(
            "/api/v1/daily-summary/apply", json=payload, headers=headers
        )

        assert second.status_code == 200
        assert await _checklist_state(db_session, category_id) == {
            b12_id: True,
            d3_id: True,
        }

    async def test_a_key_reused_with_an_added_tick_is_a_conflict(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """One more box under the same key is a new intent, not a replay.

        Answering 200 would report the box as ticked while nothing was written,
        and the key can never write it afterwards either — the tick would be
        lost for good, silently.
        """
        category_id, b12_id, d3_id = await _make_checklist_category(client, db_session)
        headers = {"Idempotency-Key": "day-key-added-tick"}

        first = await client.post(
            "/api/v1/daily-summary/apply",
            json={
                "entry_date": ENTRY_DATE,
                "checklist": [_check_payload(category_id, b12_id)],
            },
            headers=headers,
        )
        assert first.status_code == 201

        second = await client.post(
            "/api/v1/daily-summary/apply",
            json={
                "entry_date": ENTRY_DATE,
                "checklist": [
                    _check_payload(category_id, b12_id),
                    _check_payload(category_id, d3_id),
                ],
            },
            headers=headers,
        )

        assert second.status_code == 409
        assert str(category_id) in second.json()["detail"]
        # Nothing was written: D3 is still down, and no second entry appeared.
        assert await _checklist_state(db_session, category_id) == {b12_id: True}
        entries = (
            (
                await db_session.execute(
                    select(Entry).where(Entry.category_id == category_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(entries) == 1

    async def test_a_checklist_with_a_number_keeps_one_entry_a_day(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A number and a tick into one checklist category share the day's entry.

        Two rows for one (category, date) would leave every reader of the day
        guessing which one is the day — and `upsert_checklist_values` promises
        exactly one.
        """
        category_id, b12_id, d3_id = await _make_checklist_category(client, db_session)
        created = await client.post(
            f"/api/v1/categories/{category_id}/fields",
            json={"name": "Доза", "field_type": "number", "order": 3},
        )
        assert created.status_code == 201
        dose_id = created.json()["id"]

        morning = await client.put(
            "/api/v1/entries/checklist",
            json={
                "category_id": category_id,
                "entry_date": ENTRY_DATE,
                "values": {str(d3_id): True},
            },
        )
        assert morning.status_code == 200

        response = await client.post(
            "/api/v1/daily-summary/apply",
            json={
                "entry_date": ENTRY_DATE,
                "metrics": [
                    {
                        "op": "log_metric",
                        "category_id": category_id,
                        "field_id": dose_id,
                        "value": 1000,
                        "source_text": "выпил 1000 единиц",
                    }
                ],
                "checklist": [_check_payload(category_id, b12_id)],
            },
        )

        assert response.status_code == 201
        entries = (
            (
                await db_session.execute(
                    select(Entry).where(Entry.category_id == category_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(entries) == 1
        assert response.json()["entry_ids"] == [entries[0].id]
        # The morning tick survived the metric write, and the plan's tick landed.
        assert await _checklist_state(db_session, category_id) == {
            b12_id: True,
            d3_id: True,
        }
