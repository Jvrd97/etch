"""
Tests for Category CRUD operations.
"""

# [review:need-review] 175, #176
# summary: category CRUD coverage includes primary field validation and unit/quick-step persistence

import logging
from io import StringIO

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import category as category_crud
from app.models import Category, Field

PRIMARY_FIELD_REVISION = "e7a9c1b3d5f8"
PRIMARY_FIELD_PREVIOUS_REVISION = "d6f8a0c2e4b7"
FIELD_OPTIONS_REVISION = "a9c1e3f5b7d0"


@pytest.mark.asyncio
class TestCategoryCreate:
    """Tests for creating categories."""

    async def test_create_category_without_fields(self, client: AsyncClient):
        """Test creating a category without fields."""
        response = await client.post(
            "/api/v1/categories",
            json={
                "name": "Sleep",
                "description": "Track sleep quality",
                "color": "#3B82F6",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Sleep"
        assert data["description"] == "Track sleep quality"
        assert data["color"] == "#3B82F6"
        assert data["is_active"] is True
        assert "id" in data
        assert "created_at" in data

    async def test_create_category_with_fields(self, client: AsyncClient):
        """Test creating a category with fields."""
        response = await client.post(
            "/api/v1/categories",
            json={
                "name": "Sleep",
                "description": "Track sleep quality",
                "color": "#3B82F6",
                "fields": [
                    {
                        "name": "Duration (hours)",
                        "field_type": "number",
                        "is_required": True,
                        "order": 1,
                    },
                    {
                        "name": "Quality",
                        "field_type": "select",
                        "options": "poor,average,excellent",
                        "is_required": False,
                        "order": 2,
                    },
                ],
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Sleep"
        assert len(data["fields"]) == 2
        assert data["fields"][0]["name"] == "Duration (hours)"
        assert data["fields"][0]["field_type"] == "number"
        assert data["fields"][1]["name"] == "Quality"
        assert data["fields"][1]["field_type"] == "select"
        assert data["fields"][1]["options"] == "poor,average,excellent"

    async def test_field_unit_and_quick_steps_round_trip(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/categories",
            json={
                "name": "Water",
                "fields": [
                    {
                        "name": "Amount",
                        "field_type": "number",
                        "unit": "ml",
                        "quick_steps": [-250, 250, 500],
                    }
                ],
            },
        )
        assert response.status_code == 201
        category = response.json()
        field = category["fields"][0]
        assert field["unit"] == "ml"
        assert field["quick_steps"] == [-250, 250, 500]
        patched = await client.patch(
            f"/api/v1/categories/{category['id']}",
            json={"fields": [{**field, "unit": "L", "quick_steps": [0.25, 0.5]}]},
        )
        assert patched.status_code == 200
        assert patched.json()["fields"][0]["unit"] == "L"
        assert patched.json()["fields"][0]["quick_steps"] == [0.25, 0.5]

    async def test_create_category_defaults_display_mode_and_group(
        self, client: AsyncClient
    ):
        """Category created without new fields gets display_mode=form, group=None."""
        response = await client.post("/api/v1/categories", json={"name": "Sleep"})
        assert response.status_code == 201
        data = response.json()
        assert data["display_mode"] == "form"
        assert data["group"] is None

    async def test_create_category_with_display_mode_and_group(
        self, client: AsyncClient
    ):
        """Category can be created with checklist mode and a group."""
        response = await client.post(
            "/api/v1/categories",
            json={
                "name": "Vitamins",
                "display_mode": "checklist",
                "group": "Health",
                "fields": [{"name": "Taken", "field_type": "boolean"}],
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["display_mode"] == "checklist"
        assert data["group"] == "Health"

    async def test_create_category_defaults_show_in_today_to_null(
        self, client: AsyncClient
    ):
        """Без явного выбора категория остаётся под эвристикой Today."""
        response = await client.post("/api/v1/categories", json={"name": "Sleep"})
        assert response.status_code == 201
        assert response.json()["show_in_today"] is None

    @pytest.mark.parametrize("wanted", [True, False])
    async def test_create_category_with_explicit_show_in_today(
        self, client: AsyncClient, wanted: bool
    ):
        """Явный выбор пользователя сохраняется как есть, в обе стороны."""
        response = await client.post(
            "/api/v1/categories",
            json={"name": f"Sleep-{wanted}", "show_in_today": wanted},
        )
        assert response.status_code == 201
        assert response.json()["show_in_today"] is wanted

    async def test_create_category_invalid_display_mode(self, client: AsyncClient):
        """Garbage display_mode is rejected with 422."""
        response = await client.post(
            "/api/v1/categories",
            json={"name": "Vitamins", "display_mode": "carousel"},
        )
        assert response.status_code == 422

    async def test_create_category_duplicate_name(self, client: AsyncClient):
        """Test creating a category with duplicate name fails."""
        # Create first category
        await client.post(
            "/api/v1/categories", json={"name": "Sleep", "description": "Track sleep"}
        )

        # Try to create duplicate
        response = await client.post(
            "/api/v1/categories",
            json={"name": "Sleep", "description": "Another sleep tracker"},
        )
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"]


@pytest.mark.asyncio
class TestCategoryRead:
    """Tests for reading categories."""

    async def test_get_all_categories(self, client: AsyncClient):
        """Test getting all categories."""
        # Create test categories
        await client.post(
            "/api/v1/categories", json={"name": "Sleep", "description": "Track sleep"}
        )
        await client.post(
            "/api/v1/categories",
            json={"name": "Exercise", "description": "Track exercise"},
        )

        response = await client.get("/api/v1/categories")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        # Check that both categories are present (order may vary)
        names = [cat["name"] for cat in data]
        assert "Sleep" in names
        assert "Exercise" in names

    async def test_get_category_by_id(self, client: AsyncClient):
        """Test getting a specific category by ID."""
        # Create category
        create_response = await client.post(
            "/api/v1/categories", json={"name": "Sleep", "description": "Track sleep"}
        )
        category_id = create_response.json()["id"]

        # Get category
        response = await client.get(f"/api/v1/categories/{category_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == category_id
        assert data["name"] == "Sleep"

    async def test_get_nonexistent_category(self, client: AsyncClient):
        """Test getting a nonexistent category returns 404."""
        response = await client.get("/api/v1/categories/9999")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    async def test_get_active_categories_only(self, client: AsyncClient):
        """Test filtering active categories."""
        # Create active and inactive categories
        await client.post(
            "/api/v1/categories", json={"name": "Active", "is_active": True}
        )
        create_response = await client.post(
            "/api/v1/categories", json={"name": "Inactive", "is_active": True}
        )
        inactive_id = create_response.json()["id"]

        # Deactivate one
        await client.patch(
            f"/api/v1/categories/{inactive_id}", json={"is_active": False}
        )

        # Get active only
        response = await client.get("/api/v1/categories?active_only=true")
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Active"


@pytest.mark.asyncio
class TestCategoryUpdate:
    """Tests for updating categories."""

    async def test_update_category_name(self, client: AsyncClient):
        """Test updating category name."""
        # Create category
        create_response = await client.post(
            "/api/v1/categories", json={"name": "Sleep", "description": "Track sleep"}
        )
        category_id = create_response.json()["id"]

        # Update category
        response = await client.patch(
            f"/api/v1/categories/{category_id}", json={"name": "Sleep Quality"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Sleep Quality"
        assert data["description"] == "Track sleep"  # unchanged

    async def test_update_category_description_and_color(self, client: AsyncClient):
        """Test updating multiple fields."""
        # Create category
        create_response = await client.post(
            "/api/v1/categories",
            json={"name": "Sleep", "description": "Track sleep", "color": "#000000"},
        )
        category_id = create_response.json()["id"]

        # Update
        response = await client.patch(
            f"/api/v1/categories/{category_id}",
            json={"description": "Monitor sleep patterns", "color": "#FF0000"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["description"] == "Monitor sleep patterns"
        assert data["color"] == "#FF0000"
        assert data["name"] == "Sleep"  # unchanged

    async def test_update_category_display_mode_and_group(self, client: AsyncClient):
        """Existing category with a boolean field can be switched to checklist mode."""
        create_response = await client.post(
            "/api/v1/categories",
            json={
                "name": "Vitamins",
                "fields": [{"name": "Taken", "field_type": "boolean"}],
            },
        )
        category_id = create_response.json()["id"]

        response = await client.patch(
            f"/api/v1/categories/{category_id}",
            json={"display_mode": "checklist", "group": "Health"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["display_mode"] == "checklist"
        assert data["group"] == "Health"
        assert data["name"] == "Vitamins"  # unchanged

    async def test_update_pins_category_to_today(self, client: AsyncClient):
        """Категорию без числового поля можно вручную вывести на Today."""
        created = await client.post(
            "/api/v1/categories",
            json={"name": "Mood", "fields": [{"name": "Note", "field_type": "text"}]},
        )
        category_id = created.json()["id"]

        response = await client.patch(
            f"/api/v1/categories/{category_id}", json={"show_in_today": True}
        )
        assert response.status_code == 200
        assert response.json()["show_in_today"] is True

    async def test_update_hides_category_from_today_without_deleting_it(
        self, client: AsyncClient
    ):
        """Убрать с Today — не то же самое, что удалить или деактивировать."""
        created = await client.post(
            "/api/v1/categories",
            json={
                "name": "Steps",
                "fields": [{"name": "Count", "field_type": "number"}],
            },
        )
        category_id = created.json()["id"]

        response = await client.patch(
            f"/api/v1/categories/{category_id}", json={"show_in_today": False}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["show_in_today"] is False
        assert data["is_active"] is True
        assert len(data["fields"]) == 1

    async def test_update_returns_category_to_the_heuristic(self, client: AsyncClient):
        """Явно присланный null снимает переопределение, а не игнорируется."""
        created = await client.post(
            "/api/v1/categories", json={"name": "Water", "show_in_today": False}
        )
        category_id = created.json()["id"]

        response = await client.patch(
            f"/api/v1/categories/{category_id}", json={"show_in_today": None}
        )
        assert response.status_code == 200
        assert response.json()["show_in_today"] is None

    async def test_update_without_show_in_today_leaves_the_choice_alone(
        self, client: AsyncClient
    ):
        """Патч других полей не должен молча сбрасывать выбор пользователя."""
        created = await client.post(
            "/api/v1/categories", json={"name": "Reading", "show_in_today": True}
        )
        category_id = created.json()["id"]

        response = await client.patch(
            f"/api/v1/categories/{category_id}", json={"group": "Habits"}
        )
        assert response.status_code == 200
        assert response.json()["show_in_today"] is True

    async def test_update_category_invalid_display_mode(self, client: AsyncClient):
        """Garbage display_mode in PATCH is rejected with 422."""
        create_response = await client.post(
            "/api/v1/categories", json={"name": "Vitamins"}
        )
        category_id = create_response.json()["id"]

        response = await client.patch(
            f"/api/v1/categories/{category_id}", json={"display_mode": "grid"}
        )
        assert response.status_code == 422

    async def test_create_checklist_without_boolean_field_rejected(
        self, client: AsyncClient
    ):
        """POST with display_mode=checklist and no boolean field returns 422."""
        response = await client.post(
            "/api/v1/categories",
            json={
                "name": "Coffee",
                "display_mode": "checklist",
                "fields": [{"name": "Cups", "field_type": "number"}],
            },
        )
        assert response.status_code == 422
        assert "boolean" in response.json()["detail"].lower()

    async def test_create_checklist_without_any_fields_rejected(
        self, client: AsyncClient
    ):
        """POST with display_mode=checklist and empty fields returns 422."""
        response = await client.post(
            "/api/v1/categories",
            json={"name": "Coffee", "display_mode": "checklist"},
        )
        assert response.status_code == 422
        assert "boolean" in response.json()["detail"].lower()

    async def test_patch_to_checklist_without_boolean_field_rejected(
        self, client: AsyncClient
    ):
        """PATCH switching to checklist fails with 422 when no boolean field exists."""
        create_response = await client.post(
            "/api/v1/categories",
            json={
                "name": "Coffee",
                "fields": [{"name": "Cups", "field_type": "number"}],
            },
        )
        category_id = create_response.json()["id"]

        response = await client.patch(
            f"/api/v1/categories/{category_id}", json={"display_mode": "checklist"}
        )
        assert response.status_code == 422
        assert "boolean" in response.json()["detail"].lower()

        # Category is untouched by the rejected patch
        get_response = await client.get(f"/api/v1/categories/{category_id}")
        assert get_response.json()["display_mode"] == "form"

    async def test_update_nonexistent_category(self, client: AsyncClient):
        """Test updating nonexistent category returns 404."""
        response = await client.patch(
            "/api/v1/categories/9999", json={"name": "New Name"}
        )
        assert response.status_code == 404

    async def test_update_syncs_fields_add_rename_remove(self, client: AsyncClient):
        """PATCH with `fields` renames existing (by id), adds new, drops omitted."""
        create_response = await client.post(
            "/api/v1/categories",
            json={
                "name": "Vitamins",
                "fields": [
                    {"name": "D3", "field_type": "boolean", "order": 0},
                    {"name": "Zinc", "field_type": "boolean", "order": 1},
                ],
            },
        )
        category = create_response.json()
        d3_id = category["fields"][0]["id"]
        # Keep D3 (renamed, same id), drop Zinc, add Magnesium.
        response = await client.patch(
            f"/api/v1/categories/{category['id']}",
            json={
                "fields": [
                    {
                        "id": d3_id,
                        "name": "Vitamin D3",
                        "field_type": "boolean",
                        "order": 0,
                    },
                    {"name": "Magnesium", "field_type": "boolean", "order": 1},
                ]
            },
        )
        assert response.status_code == 200
        fields = {f["name"]: f for f in response.json()["fields"]}
        assert set(fields) == {"Vitamin D3", "Magnesium"}
        assert fields["Vitamin D3"]["id"] == d3_id  # same row, kept its id

    async def test_reordered_fields_come_back_in_the_new_order(
        self, client: AsyncClient
    ):
        """PATCH меняет только `order` — и ответы отдают поля уже в этом порядке.

        Перестановка не трогает ни id, ни порядок строк в таблице, поэтому без
        сортировки в relationship клиент получал бы прежнюю последовательность и
        решил бы, что сохранение не прошло.
        """
        create_response = await client.post(
            "/api/v1/categories",
            json={
                "name": "Sleep",
                "fields": [
                    {"name": "Hours", "field_type": "number", "order": 0},
                    {"name": "Quality", "field_type": "text", "order": 1},
                ],
            },
        )
        category = create_response.json()
        assert [f["name"] for f in category["fields"]] == ["Hours", "Quality"]
        hours_id, quality_id = (f["id"] for f in category["fields"])

        patch_response = await client.patch(
            f"/api/v1/categories/{category['id']}",
            json={
                "fields": [
                    {
                        "id": quality_id,
                        "name": "Quality",
                        "field_type": "text",
                        "order": 0,
                    },
                    {
                        "id": hours_id,
                        "name": "Hours",
                        "field_type": "number",
                        "order": 1,
                    },
                ]
            },
        )
        assert patch_response.status_code == 200
        assert [f["id"] for f in patch_response.json()["fields"]] == [
            quality_id,
            hours_id,
        ]

        # Перечитываем отдельным запросом: порядок должен пережить рефетч, а не
        # быть побочным эффектом порядка элементов в теле PATCH.
        get_response = await client.get(f"/api/v1/categories/{category['id']}")
        fields = get_response.json()["fields"]
        assert [f["name"] for f in fields] == ["Quality", "Hours"]
        assert [f["order"] for f in fields] == [0, 1]

        # И в списке категорий — им пользуется экран Today.
        list_response = await client.get("/api/v1/categories")
        listed = next(c for c in list_response.json() if c["id"] == category["id"])
        assert [f["name"] for f in listed["fields"]] == ["Quality", "Hours"]

    async def test_update_fields_preserves_entry_history(self, client: AsyncClient):
        """Renaming a field (same id) keeps existing entry values intact."""
        create_response = await client.post(
            "/api/v1/categories",
            json={
                "name": "Sleep",
                "fields": [{"name": "Hours", "field_type": "number", "order": 0}],
            },
        )
        category = create_response.json()
        field_id = category["fields"][0]["id"]

        await client.post(
            "/api/v1/entries",
            json={
                "category_id": category["id"],
                "entry_date": "2024-01-15",
                "values": [{"field_id": field_id, "value": "8"}],
            },
        )

        # Rename the field via category update (same id).
        response = await client.patch(
            f"/api/v1/categories/{category['id']}",
            json={
                "fields": [
                    {
                        "id": field_id,
                        "name": "Sleep hours",
                        "field_type": "number",
                        "order": 0,
                    }
                ]
            },
        )
        assert response.status_code == 200

        entries = await client.get(f"/api/v1/entries?category_id={category['id']}")
        values = entries.json()[0]["values"]
        assert values[0]["field_id"] == field_id
        assert values[0]["value"] == "8"

    async def test_update_without_ids_creates_new_fields(self, client: AsyncClient):
        """A field payload without an id is always treated as a new field.

        The identity fallback (matching id-less fields by name/type) is gone: the
        only way to update a field in place is to send its id. An id-less item —
        even one whose name and type match an existing field — creates a fresh
        field and drops the unmatched existing one. Behaviour is now predictable,
        no longer dependent on a name/type coincidence.
        """
        create_response = await client.post(
            "/api/v1/categories",
            json={
                "name": "Meditation",
                "fields": [
                    {"name": "Time", "field_type": "duration", "order": 0},
                ],
            },
        )
        category = create_response.json()
        old_field_id = category["fields"][0]["id"]

        response = await client.patch(
            f"/api/v1/categories/{category['id']}",
            json={
                "fields": [
                    {"name": "Time", "field_type": "duration", "order": 0},
                ],
            },
        )
        assert response.status_code == 200
        result_fields = response.json()["fields"]
        assert len(result_fields) == 1
        assert result_fields[0]["name"] == "Time"
        assert result_fields[0]["id"] != old_field_id

    async def test_update_without_ids_still_drops_removed_fields(
        self, client: AsyncClient
    ):
        """Fields left out of an id-less payload are dropped, not resurrected."""
        create_response = await client.post(
            "/api/v1/categories",
            json={
                "name": "Sleep",
                "fields": [
                    {"name": "Hours", "field_type": "number", "order": 0},
                    {"name": "Quality", "field_type": "text", "order": 1},
                ],
            },
        )
        category = create_response.json()

        response = await client.patch(
            f"/api/v1/categories/{category['id']}",
            json={"fields": [{"name": "Hours", "field_type": "number", "order": 0}]},
        )
        assert response.status_code == 200
        assert [f["name"] for f in response.json()["fields"]] == ["Hours"]

    async def test_update_omitting_fields_leaves_them_untouched(
        self, client: AsyncClient
    ):
        """PATCH without `fields` must not delete existing fields."""
        create_response = await client.post(
            "/api/v1/categories",
            json={
                "name": "Sleep",
                "fields": [{"name": "Hours", "field_type": "number"}],
            },
        )
        category_id = create_response.json()["id"]

        response = await client.patch(
            f"/api/v1/categories/{category_id}", json={"name": "Sleep tracker"}
        )
        assert response.status_code == 200
        assert len(response.json()["fields"]) == 1

    async def test_dropping_a_field_with_history_is_logged(
        self, client: AsyncClient, caplog: pytest.LogCaptureFixture
    ):
        """Cascading a field's entry_values away must leave a trace in the log.

        An id-less PATCH reads every item as a new field, so an existing field
        absent from the payload is dropped and its entry_values cascade away.
        That path destroys history, so it must not be silent.
        """
        create_response = await client.post(
            "/api/v1/categories",
            json={
                "name": "Running",
                "fields": [{"name": "Distance", "field_type": "number", "order": 0}],
            },
        )
        category = create_response.json()
        field_id = category["fields"][0]["id"]

        await client.post(
            "/api/v1/entries",
            json={
                "category_id": category["id"],
                "entry_date": "2024-01-15",
                "values": [{"field_id": field_id, "value": "5"}],
            },
        )

        with caplog.at_level(logging.WARNING, logger="app.crud.category"):
            response = await client.patch(
                f"/api/v1/categories/{category['id']}",
                json={"fields": [{"name": "Kilometres", "field_type": "number"}]},
            )
        assert response.status_code == 200

        dropped = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert dropped, "dropping a field with history must be logged"
        assert str(field_id) in caplog.text
        assert "Distance" not in caplog.text, "field name is user data, keep it out"

    async def test_patch_to_checklist_with_boolean_field_in_same_call(
        self, client: AsyncClient
    ):
        """Switching to checklist while adding a boolean field in one PATCH succeeds."""
        create_response = await client.post(
            "/api/v1/categories",
            json={
                "name": "Coffee",
                "fields": [{"name": "Cups", "field_type": "number"}],
            },
        )
        category = create_response.json()
        cups_id = category["fields"][0]["id"]

        response = await client.patch(
            f"/api/v1/categories/{category['id']}",
            json={
                "display_mode": "checklist",
                "fields": [
                    {
                        "id": cups_id,
                        "name": "Cups",
                        "field_type": "number",
                        "order": 0,
                    },
                    {"name": "Had coffee", "field_type": "boolean", "order": 1},
                ],
            },
        )
        assert response.status_code == 200
        assert response.json()["display_mode"] == "checklist"


@pytest.mark.asyncio
class TestCategoryDelete:
    """Tests for deleting categories."""

    async def test_delete_category(self, client: AsyncClient):
        """Test deleting a category."""
        # Create category
        create_response = await client.post(
            "/api/v1/categories", json={"name": "Sleep", "description": "Track sleep"}
        )
        category_id = create_response.json()["id"]

        # Delete category
        response = await client.delete(f"/api/v1/categories/{category_id}")
        assert response.status_code == 204

        # Verify it's deleted
        get_response = await client.get(f"/api/v1/categories/{category_id}")
        assert get_response.status_code == 404

    async def test_delete_nonexistent_category(self, client: AsyncClient):
        """Test deleting nonexistent category returns 404."""
        response = await client.delete("/api/v1/categories/9999")
        assert response.status_code == 404


@pytest.mark.asyncio
class TestCategoryPrimaryField:
    """Explicit selection of the field represented by a category table column."""

    async def test_category_defaults_primary_field_to_null(
        self, client: AsyncClient
    ) -> None:
        response = await client.post("/api/v1/categories", json={"name": "Sleep"})

        assert response.status_code == 201
        assert response.json()["primary_field_id"] is None

    async def test_category_accepts_own_primary_field_and_explicit_null(
        self, client: AsyncClient
    ) -> None:
        created = await client.post(
            "/api/v1/categories",
            json={
                "name": "Workout",
                "fields": [
                    {"name": "Done", "field_type": "boolean", "order": 0},
                    {"name": "Quantity", "field_type": "number", "order": 1},
                ],
            },
        )
        category = created.json()
        quantity_id = next(
            field["id"] for field in category["fields"] if field["name"] == "Quantity"
        )

        selected = await client.patch(
            f"/api/v1/categories/{category['id']}",
            json={"primary_field_id": quantity_id},
        )
        assert selected.status_code == 200
        assert selected.json()["primary_field_id"] == quantity_id

        cleared = await client.patch(
            f"/api/v1/categories/{category['id']}",
            json={"primary_field_id": None},
        )
        assert cleared.status_code == 200
        assert cleared.json()["primary_field_id"] is None

    async def test_foreign_primary_field_is_rejected_before_update(
        self, client: AsyncClient
    ) -> None:
        first = (
            await client.post(
                "/api/v1/categories",
                json={
                    "name": "Workout",
                    "fields": [{"name": "Quantity", "field_type": "number"}],
                },
            )
        ).json()
        second = (
            await client.post(
                "/api/v1/categories",
                json={
                    "name": "Sleep",
                    "fields": [{"name": "Hours", "field_type": "number"}],
                },
            )
        ).json()
        foreign_field_id = second["fields"][0]["id"]

        response = await client.patch(
            f"/api/v1/categories/{first['id']}",
            json={"name": "Must not persist", "primary_field_id": foreign_field_id},
        )

        assert response.status_code == 422
        unchanged = await client.get(f"/api/v1/categories/{first['id']}")
        assert unchanged.json()["name"] == "Workout"
        assert unchanged.json()["primary_field_id"] is None

    async def test_same_save_deletion_clears_selected_primary_field(
        self, client: AsyncClient
    ) -> None:
        created = (
            await client.post(
                "/api/v1/categories",
                json={
                    "name": "Workout",
                    "fields": [
                        {"name": "Done", "field_type": "boolean", "order": 0},
                        {"name": "Quantity", "field_type": "number", "order": 1},
                    ],
                },
            )
        ).json()
        done, quantity = created["fields"]
        await client.patch(
            f"/api/v1/categories/{created['id']}",
            json={"primary_field_id": quantity["id"]},
        )

        response = await client.patch(
            f"/api/v1/categories/{created['id']}",
            json={
                "primary_field_id": quantity["id"],
                "fields": [
                    {
                        "id": done["id"],
                        "name": done["name"],
                        "field_type": done["field_type"],
                        "order": done["order"],
                    }
                ],
            },
        )

        assert response.status_code == 200
        assert response.json()["primary_field_id"] is None

    async def test_create_rejects_non_null_primary_field_id(
        self, client: AsyncClient
    ) -> None:
        existing = (
            await client.post(
                "/api/v1/categories",
                json={
                    "name": "Existing",
                    "fields": [{"name": "Quantity", "field_type": "number"}],
                },
            )
        ).json()

        response = await client.post(
            "/api/v1/categories",
            json={
                "name": "New category",
                "primary_field_id": existing["fields"][0]["id"],
            },
        )

        assert response.status_code == 422

    async def test_batch_create_rejects_non_null_primary_field_id(
        self, client: AsyncClient
    ) -> None:
        existing = (
            await client.post(
                "/api/v1/categories",
                json={
                    "name": "Existing",
                    "fields": [{"name": "Quantity", "field_type": "number"}],
                },
            )
        ).json()

        response = await client.post(
            "/api/v1/categories/batch",
            json={
                "operations": [
                    {
                        "op": "create_category",
                        "name": "New category",
                        "primary_field_id": existing["fields"][0]["id"],
                    }
                ]
            },
        )

        assert response.status_code == 422
        assert response.json()["detail"] == category_crud.PRIMARY_FIELD_ON_CREATE_DETAIL

    async def test_database_field_delete_sets_primary_field_to_null(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        created = (
            await client.post(
                "/api/v1/categories",
                json={
                    "name": "Workout",
                    "fields": [{"name": "Quantity", "field_type": "number"}],
                },
            )
        ).json()
        field_id = created["fields"][0]["id"]
        selected = await client.patch(
            f"/api/v1/categories/{created['id']}",
            json={"primary_field_id": field_id},
        )
        assert selected.status_code == 200

        field = await db_session.get(Field, field_id)
        assert field is not None
        await db_session.delete(field)
        await db_session.commit()
        db_session.expire_all()

        response = await client.get(f"/api/v1/categories/{created['id']}")
        assert response.status_code == 200
        assert response.json()["primary_field_id"] is None


def _primary_field_migration_sql(revision_range: str, *, downgrade: bool) -> str:
    config = Config()
    config.set_main_option("script_location", "alembic")
    buffer = StringIO()
    config.output_buffer = buffer
    runner = command.downgrade if downgrade else command.upgrade
    runner(config, revision_range, sql=True)
    return buffer.getvalue().lower()


def test_primary_field_migration_is_reversible_and_keeps_one_head() -> None:
    config = Config()
    config.set_main_option("script_location", "alembic")
    assert len(ScriptDirectory.from_config(config).get_heads()) == 1

    upgrade_sql = _primary_field_migration_sql(
        f"{PRIMARY_FIELD_PREVIOUS_REVISION}:{PRIMARY_FIELD_REVISION}", downgrade=False
    )
    assert "add column primary_field_id integer" in upgrade_sql
    assert "on delete set null" in upgrade_sql

    downgrade_sql = _primary_field_migration_sql(
        f"{PRIMARY_FIELD_REVISION}:{PRIMARY_FIELD_PREVIOUS_REVISION}", downgrade=True
    )
    assert "drop constraint fk_categories_primary_field_id_fields" in downgrade_sql
    assert "drop column primary_field_id" in downgrade_sql


def test_field_options_migration_is_reversible_and_is_the_only_head() -> None:
    config = Config()
    config.set_main_option("script_location", "alembic")
    assert ScriptDirectory.from_config(config).get_heads() == [FIELD_OPTIONS_REVISION]
    upgrade_sql = _primary_field_migration_sql(
        f"f8b0d2e4a6c9:{FIELD_OPTIONS_REVISION}", downgrade=False
    )
    assert "add column unit varchar(50)" in upgrade_sql
    assert "add column quick_steps json" in upgrade_sql
    downgrade_sql = _primary_field_migration_sql(
        f"{FIELD_OPTIONS_REVISION}:f8b0d2e4a6c9", downgrade=True
    )
    assert "drop column quick_steps" in downgrade_sql
    assert "drop column unit" in downgrade_sql


@pytest.mark.asyncio
class TestCategoryFields:
    """Tests for category field operations."""

    async def test_add_field_to_category(self, client: AsyncClient):
        """Test adding a field to existing category."""
        # Create category
        create_response = await client.post(
            "/api/v1/categories", json={"name": "Sleep", "description": "Track sleep"}
        )
        category_id = create_response.json()["id"]

        # Add field
        response = await client.post(
            f"/api/v1/categories/{category_id}/fields",
            json={"name": "Duration", "field_type": "number", "is_required": True},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Duration"
        assert data["field_type"] == "number"
        assert data["is_required"] is True
        assert data["category_id"] == category_id

    async def test_add_field_to_nonexistent_category(self, client: AsyncClient):
        """Test adding field to nonexistent category fails."""
        response = await client.post(
            "/api/v1/categories/9999/fields",
            json={"name": "Test", "field_type": "text"},
        )
        assert response.status_code == 404


@pytest.mark.asyncio
class TestCategoryBatch:
    """Tests for the transactional POST /categories/batch endpoint."""

    async def test_apply_plan_creates_categories_and_fields(self, client: AsyncClient):
        """A plan of three categories and two fields applies in one request."""
        # Pre-existing category the add_field ops target.
        sport = await client.post(
            "/api/v1/categories",
            json={
                "name": "Sport",
                "fields": [{"name": "Reps", "field_type": "number"}],
            },
        )
        sport_id = sport.json()["id"]

        response = await client.post(
            "/api/v1/categories/batch",
            json={
                "operations": [
                    {
                        "op": "create_category",
                        "name": "Sleep",
                        "fields": [
                            {"name": "Hours", "field_type": "number"},
                            {"name": "Quality", "field_type": "select"},
                        ],
                    },
                    {"op": "create_category", "name": "Water"},
                    {"op": "create_category", "name": "Meditation"},
                    {
                        "op": "add_field",
                        "category_id": sport_id,
                        "field": {"name": "Pulse", "field_type": "number"},
                    },
                    {
                        "op": "add_field",
                        "category_id": sport_id,
                        "field": {"name": "Duration", "field_type": "duration"},
                    },
                ]
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert {c["name"] for c in body["categories"]} == {
            "Sleep",
            "Water",
            "Meditation",
        }
        assert {f["name"] for f in body["fields"]} == {"Pulse", "Duration"}

        listing = await client.get("/api/v1/categories")
        names = {c["name"] for c in listing.json()}
        assert {"Sleep", "Water", "Meditation", "Sport"} <= names

    async def test_failure_on_second_op_leaves_no_records(self, client: AsyncClient):
        """An add_field to a missing category rolls back the whole plan."""
        response = await client.post(
            "/api/v1/categories/batch",
            json={
                "operations": [
                    {"op": "create_category", "name": "Sleep"},
                    {
                        "op": "add_field",
                        "category_id": 9999,
                        "field": {"name": "Pulse", "field_type": "number"},
                    },
                ]
            },
        )
        assert response.status_code == 400

        listing = await client.get("/api/v1/categories")
        assert [c for c in listing.json() if c["name"] == "Sleep"] == []

    async def test_duplicate_name_rejected(self, client: AsyncClient):
        """A create_category name that already exists returns 400, DB unchanged."""
        await client.post("/api/v1/categories", json={"name": "Sleep"})

        response = await client.post(
            "/api/v1/categories/batch",
            json={
                "operations": [
                    {"op": "create_category", "name": "Water"},
                    {"op": "create_category", "name": "Sleep"},
                ]
            },
        )
        assert response.status_code == 400

        listing = await client.get("/api/v1/categories")
        assert [c for c in listing.json() if c["name"] == "Water"] == []

    async def test_duplicate_name_within_batch_rejected(self, client: AsyncClient):
        """Two create_category ops with the same name in one plan return 400."""
        response = await client.post(
            "/api/v1/categories/batch",
            json={
                "operations": [
                    {"op": "create_category", "name": "Sleep"},
                    {"op": "create_category", "name": "Sleep"},
                ]
            },
        )
        assert response.status_code == 400

        listing = await client.get("/api/v1/categories")
        assert [c for c in listing.json() if c["name"] == "Sleep"] == []

    async def test_add_field_to_missing_category_rejected(self, client: AsyncClient):
        """add_field with an unknown category_id returns 400."""
        response = await client.post(
            "/api/v1/categories/batch",
            json={
                "operations": [
                    {
                        "op": "add_field",
                        "category_id": 9999,
                        "field": {"name": "Pulse", "field_type": "number"},
                    }
                ]
            },
        )
        assert response.status_code == 400

    async def test_checklist_without_boolean_field_rejected(self, client: AsyncClient):
        """A checklist create_category with no boolean field is rejected with 422."""
        response = await client.post(
            "/api/v1/categories/batch",
            json={
                "operations": [
                    {
                        "op": "create_category",
                        "name": "Vitamins",
                        "display_mode": "checklist",
                        "fields": [{"name": "Cups", "field_type": "number"}],
                    }
                ]
            },
        )
        assert response.status_code == 422
        assert "boolean" in response.json()["detail"].lower()

        listing = await client.get("/api/v1/categories")
        assert [c for c in listing.json() if c["name"] == "Vitamins"] == []


@pytest.mark.asyncio
class TestGetCategoriesLimit:
    """Tests for the limit parameter of crud.category.get_categories."""

    async def test_limit_none_returns_all(self, db_session: AsyncSession) -> None:
        """limit=None disables pagination and returns every active category."""
        for i in range(3):
            db_session.add(Category(name=f"Cat {i}"))
        await db_session.commit()

        limited = await category_crud.get_categories(db_session, limit=2)
        assert len(limited) == 2

        unlimited = await category_crud.get_categories(db_session, limit=None)
        assert len(unlimited) == 3
