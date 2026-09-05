"""
Tests for the table view endpoint (per-day aggregation).
"""

# [review:need-review] 175
# summary: table metadata tests cover explicit primary field selection and legacy fallback
import logging
from typing import Any, cast

import pytest
from httpx import AsyncClient

from app.crud.table import _category_meta
from app.models import Category, Field
from app.models.field import FieldType


@pytest.fixture
async def table_category(client: AsyncClient) -> dict:
    """Category with number, boolean and text fields for table tests."""
    response = await client.post(
        "/api/v1/categories",
        json={
            "name": "Workout",
            "description": "Track workouts",
            "fields": [
                {"name": "Pushups", "field_type": "number", "order": 1},
                {"name": "Done", "field_type": "boolean", "order": 2},
                {"name": "Comment", "field_type": "text", "order": 3},
            ],
        },
    )
    return response.json()


def _field_id(category: dict, name: str) -> int:
    return next(f["id"] for f in category["fields"] if f["name"] == name)


def _cell(day: dict, field_id: int) -> dict:
    return next(c for c in day["cells"] if c["field_id"] == field_id)


def _day(data: dict, date_str: str) -> dict:
    return next(d for d in data["days"] if d["date"] == date_str)


async def _create_entry(
    client: AsyncClient,
    category_id: int,
    entry_date: str,
    values: list[dict],
) -> dict:
    response = await client.post(
        "/api/v1/entries",
        json={
            "category_id": category_id,
            "entry_date": entry_date,
            "values": values,
        },
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
class TestTableAggregation:
    """Tests for GET /api/v1/table aggregation logic."""

    async def test_number_field_is_summed_per_day(
        self, client: AsyncClient, table_category: dict
    ):
        """20 + 22 pushups in one day -> cell value 42, entry_count 2."""
        pushups_id = _field_id(table_category, "Pushups")
        await _create_entry(
            client,
            table_category["id"],
            "2024-01-15",
            [{"field_id": pushups_id, "value": "20"}],
        )
        await _create_entry(
            client,
            table_category["id"],
            "2024-01-15",
            [{"field_id": pushups_id, "value": "22"}],
        )

        response = await client.get(
            "/api/v1/table?date_from=2024-01-15&date_to=2024-01-15"
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["days"]) == 1
        cell = _cell(_day(data, "2024-01-15"), pushups_id)
        assert cell["category_id"] == table_category["id"]
        assert cell["aggregated_value"] == "42"
        assert cell["entry_count"] == 2

    async def test_duration_field_is_summed_per_day(self, client: AsyncClient):
        """DURATION values (elapsed seconds) sum like numbers: 1200 + 2400 -> 3600."""
        category = (
            await client.post(
                "/api/v1/categories",
                json={
                    "name": "Running",
                    "fields": [
                        {"name": "Elapsed", "field_type": "duration", "order": 1},
                    ],
                },
            )
        ).json()
        elapsed_id = _field_id(category, "Elapsed")
        await _create_entry(
            client,
            category["id"],
            "2024-02-01",
            [{"field_id": elapsed_id, "value": "1200"}],
        )
        await _create_entry(
            client,
            category["id"],
            "2024-02-01",
            [{"field_id": elapsed_id, "value": "2400"}],
        )

        response = await client.get(
            "/api/v1/table?date_from=2024-02-01&date_to=2024-02-01"
        )
        assert response.status_code == 200
        data = response.json()
        cell = _cell(_day(data, "2024-02-01"), elapsed_id)
        assert cell["aggregated_value"] == "3600"
        assert cell["entry_count"] == 2
        meta = next(c for c in data["categories"] if c["id"] == category["id"])
        assert meta["primary_field_type"] == "duration"

    async def test_empty_day_has_no_cells(
        self, client: AsyncClient, table_category: dict
    ):
        """A day in range without entries is present with an empty cells list."""
        pushups_id = _field_id(table_category, "Pushups")
        await _create_entry(
            client,
            table_category["id"],
            "2024-01-15",
            [{"field_id": pushups_id, "value": "10"}],
        )

        response = await client.get(
            "/api/v1/table?date_from=2024-01-15&date_to=2024-01-16"
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["days"]) == 2
        assert _day(data, "2024-01-16")["cells"] == []

    async def test_boolean_field_aggregates_with_any(
        self, client: AsyncClient, table_category: dict
    ):
        """Boolean field: any true value in the day -> true."""
        done_id = _field_id(table_category, "Done")
        await _create_entry(
            client,
            table_category["id"],
            "2024-01-15",
            [{"field_id": done_id, "value": "false"}],
        )
        await _create_entry(
            client,
            table_category["id"],
            "2024-01-15",
            [{"field_id": done_id, "value": "true"}],
        )
        await _create_entry(
            client,
            table_category["id"],
            "2024-01-16",
            [{"field_id": done_id, "value": "false"}],
        )

        response = await client.get(
            "/api/v1/table?date_from=2024-01-15&date_to=2024-01-16"
        )
        assert response.status_code == 200
        data = response.json()
        cell_15 = _cell(_day(data, "2024-01-15"), done_id)
        assert cell_15["aggregated_value"] == "true"
        assert cell_15["entry_count"] == 2
        cell_16 = _cell(_day(data, "2024-01-16"), done_id)
        assert cell_16["aggregated_value"] == "false"
        assert cell_16["entry_count"] == 1

    async def test_text_field_takes_last_value_by_created_at(
        self, client: AsyncClient, table_category: dict
    ):
        """Text field: the value of the most recently created entry wins."""
        comment_id = _field_id(table_category, "Comment")
        await _create_entry(
            client,
            table_category["id"],
            "2024-01-15",
            [{"field_id": comment_id, "value": "morning"}],
        )
        await _create_entry(
            client,
            table_category["id"],
            "2024-01-15",
            [{"field_id": comment_id, "value": "evening"}],
        )

        response = await client.get(
            "/api/v1/table?date_from=2024-01-15&date_to=2024-01-15"
        )
        assert response.status_code == 200
        data = response.json()
        cell = _cell(_day(data, "2024-01-15"), comment_id)
        assert cell["aggregated_value"] == "evening"
        assert cell["entry_count"] == 2

    async def test_range_boundaries_are_inclusive(
        self, client: AsyncClient, table_category: dict
    ):
        """Entries on date_from/date_to are included, outside the range excluded."""
        pushups_id = _field_id(table_category, "Pushups")
        for entry_date, value in [
            ("2024-01-14", "1"),
            ("2024-01-15", "2"),
            ("2024-01-17", "3"),
            ("2024-01-18", "4"),
        ]:
            await _create_entry(
                client,
                table_category["id"],
                entry_date,
                [{"field_id": pushups_id, "value": value}],
            )

        response = await client.get(
            "/api/v1/table?date_from=2024-01-15&date_to=2024-01-17"
        )
        assert response.status_code == 200
        data = response.json()
        assert [d["date"] for d in data["days"]] == [
            "2024-01-15",
            "2024-01-16",
            "2024-01-17",
        ]
        assert _cell(_day(data, "2024-01-15"), pushups_id)["aggregated_value"] == "2"
        assert _day(data, "2024-01-16")["cells"] == []
        assert _cell(_day(data, "2024-01-17"), pushups_id)["aggregated_value"] == "3"

    async def test_non_numeric_value_in_number_field_is_skipped_and_logged(
        self,
        client: AsyncClient,
        table_category: dict,
        caplog: pytest.LogCaptureFixture,
    ):
        """Non-numeric text in a number field: sum uses valid values, warning is logged."""
        pushups_id = _field_id(table_category, "Pushups")
        await _create_entry(
            client,
            table_category["id"],
            "2024-01-15",
            [{"field_id": pushups_id, "value": "20"}],
        )
        await _create_entry(
            client,
            table_category["id"],
            "2024-01-15",
            [{"field_id": pushups_id, "value": "not-a-number"}],
        )
        await _create_entry(
            client,
            table_category["id"],
            "2024-01-15",
            [{"field_id": pushups_id, "value": "22"}],
        )

        with caplog.at_level(logging.WARNING, logger="app.crud.table"):
            response = await client.get(
                "/api/v1/table?date_from=2024-01-15&date_to=2024-01-15"
            )
        assert response.status_code == 200
        data = response.json()
        cell = _cell(_day(data, "2024-01-15"), pushups_id)
        assert cell["aggregated_value"] == "42"
        assert cell["entry_count"] == 3

        warnings = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING
            and r.message == "non-numeric value in number field"
        ]
        assert len(warnings) == 1
        # extra={} attaches dynamic attributes to the LogRecord
        assert warnings[0].__dict__["field_id"] == pushups_id
        assert isinstance(warnings[0].__dict__["entry_id"], int)
        # PII-safe: the raw value must not leak into the log record
        assert "not-a-number" not in warnings[0].getMessage()


async def _create_category(
    client: AsyncClient,
    name: str,
    group: str | None,
    fields: list[dict[str, Any]],
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/categories",
        json={"name": name, "group": group, "fields": fields},
    )
    assert response.status_code == 201
    return cast("dict[str, Any]", response.json())


@pytest.mark.asyncio
class TestTableCategoryMeta:
    """Tests for category metadata (group, primary field) in GET /api/v1/table."""

    async def test_categories_metadata_includes_group(
        self, client: AsyncClient
    ) -> None:
        """Two groups + a category without group: group is passed through, None kept."""
        await _create_category(
            client,
            "Push-ups",
            "Sport",
            [{"name": "Count", "field_type": "number", "order": 1}],
        )
        await _create_category(
            client,
            "Squats",
            "Sport",
            [{"name": "Count", "field_type": "number", "order": 1}],
        )
        await _create_category(
            client,
            "Mood",
            None,
            [{"name": "Note", "field_type": "text", "order": 1}],
        )

        response = await client.get(
            "/api/v1/table?date_from=2024-01-15&date_to=2024-01-15"
        )
        assert response.status_code == 200
        data = response.json()
        by_name = {c["name"]: c for c in data["categories"]}
        assert by_name["Push-ups"]["group"] == "Sport"
        assert by_name["Squats"]["group"] == "Sport"
        assert by_name["Mood"]["group"] is None
        assert by_name["Push-ups"]["display_mode"] == "form"

    async def test_primary_field_is_first_by_order(self, client: AsyncClient) -> None:
        """Primary field of a category is its first field by order."""
        category = await _create_category(
            client,
            "Running",
            "Sport",
            [
                {"name": "Comment", "field_type": "text", "order": 2},
                {"name": "Distance", "field_type": "number", "order": 1},
            ],
        )
        distance_id = _field_id(category, "Distance")

        response = await client.get(
            "/api/v1/table?date_from=2024-01-15&date_to=2024-01-15"
        )
        assert response.status_code == 200
        data = response.json()
        meta = next(c for c in data["categories"] if c["id"] == category["id"])
        assert meta["primary_field_id"] == distance_id
        assert meta["primary_field_name"] == "Distance"
        assert meta["primary_field_type"] == "number"

    async def test_category_without_fields_has_no_primary_field(
        self, client: AsyncClient
    ) -> None:
        """A category with no fields is present with primary_field_id None."""
        category = await _create_category(client, "Empty", None, [])

        response = await client.get(
            "/api/v1/table?date_from=2024-01-15&date_to=2024-01-15"
        )
        assert response.status_code == 200
        data = response.json()
        meta = next(c for c in data["categories"] if c["id"] == category["id"])
        assert meta["primary_field_id"] is None
        assert meta["primary_field_name"] is None
        assert meta["primary_field_type"] is None


@pytest.mark.asyncio
class TestTableRangeValidation:
    """Tests for date range validation of GET /api/v1/table."""

    async def test_range_longer_than_max_days_returns_422(self, client: AsyncClient):
        """A range longer than MAX_RANGE_DAYS is rejected with 422."""
        response = await client.get(
            "/api/v1/table?date_from=2024-01-01&date_to=2025-01-01"
        )
        assert response.status_code == 422
        assert "366" in response.json()["detail"]


@pytest.mark.asyncio
class TestExplicitTablePrimaryField:
    """The explicit category choice wins without changing legacy fallback."""

    async def test_table_uses_explicit_primary_field(self, client: AsyncClient) -> None:
        category = await _create_category(
            client,
            "Workout",
            "Sport",
            [
                {"name": "Done", "field_type": "boolean", "order": 0},
                {"name": "Quantity", "field_type": "number", "order": 1},
            ],
        )
        quantity_id = _field_id(category, "Quantity")
        selected = await client.patch(
            f"/api/v1/categories/{category['id']}",
            json={"primary_field_id": quantity_id},
        )
        assert selected.status_code == 200

        response = await client.get(
            "/api/v1/table?date_from=2024-01-15&date_to=2024-01-15"
        )
        assert response.status_code == 200
        meta = next(
            item
            for item in response.json()["categories"]
            if item["id"] == category["id"]
        )
        assert meta["primary_field_id"] == quantity_id
        assert meta["primary_field_name"] == "Quantity"
        assert meta["primary_field_type"] == "number"


def test_category_meta_falls_back_when_selected_field_is_missing() -> None:
    category = Category(
        id=1,
        name="Workout",
        display_mode="form",
        group=None,
        primary_field_id=999,
    )
    category.fields = [
        Field(
            id=10,
            category_id=1,
            name="Done",
            field_type=FieldType.BOOLEAN,
            order=0,
        ),
        Field(
            id=11,
            category_id=1,
            name="Quantity",
            field_type=FieldType.NUMBER,
            order=1,
        ),
    ]

    meta = _category_meta(category)

    assert meta.primary_field_id == 10
    assert meta.primary_field_name == "Done"
    assert meta.primary_field_type == "boolean"
