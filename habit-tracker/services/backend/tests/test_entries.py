"""
Tests for Entry CRUD operations.
"""

# [review:need-review] PHASE-01/73-dashboard-hero-today-ring
# summary: added TestEntrySort — the default order is unchanged, created_at_desc returns the last written entry first, limit narrows it to one, and an unknown sort is a 422
import pytest
from httpx import AsyncClient
from datetime import date


@pytest.fixture
async def sample_category(client: AsyncClient) -> dict:
    """Create a sample category with fields for testing."""
    response = await client.post(
        "/api/v1/categories",
        json={
            "name": "Sleep",
            "description": "Track sleep quality",
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
                    "order": 2,
                },
            ],
        },
    )
    return response.json()


@pytest.mark.asyncio
class TestEntryCreate:
    """Tests for creating entries."""

    async def test_create_entry(self, client: AsyncClient, sample_category: dict):
        """Test creating a basic entry."""
        field_ids = [f["id"] for f in sample_category["fields"]]

        response = await client.post(
            "/api/v1/entries",
            json={
                "category_id": sample_category["id"],
                "entry_date": "2024-01-15",
                "notes": "Good night sleep",
                "values": [
                    {"field_id": field_ids[0], "value": "8"},
                    {"field_id": field_ids[1], "value": "excellent"},
                ],
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["category_id"] == sample_category["id"]
        assert data["entry_date"] == "2024-01-15"
        assert data["notes"] == "Good night sleep"
        assert len(data["values"]) == 2
        assert data["values"][0]["value"] == "8"
        assert data["values"][1]["value"] == "excellent"

    async def test_create_entry_without_notes(
        self, client: AsyncClient, sample_category: dict
    ):
        """Test creating entry without notes."""
        field_ids = [f["id"] for f in sample_category["fields"]]

        response = await client.post(
            "/api/v1/entries",
            json={
                "category_id": sample_category["id"],
                "entry_date": "2024-01-15",
                "values": [{"field_id": field_ids[0], "value": "7"}],
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["notes"] is None or data["notes"] == ""

    async def test_create_entry_with_current_date(
        self, client: AsyncClient, sample_category: dict
    ):
        """Test creating entry with today's date."""
        field_ids = [f["id"] for f in sample_category["fields"]]
        today = date.today().isoformat()

        response = await client.post(
            "/api/v1/entries",
            json={
                "category_id": sample_category["id"],
                "entry_date": today,
                "values": [{"field_id": field_ids[0], "value": "8"}],
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["entry_date"] == today


@pytest.mark.asyncio
class TestEntryRead:
    """Tests for reading entries."""

    async def test_get_all_entries(self, client: AsyncClient, sample_category: dict):
        """Test getting all entries."""
        field_ids = [f["id"] for f in sample_category["fields"]]

        # Create multiple entries
        for i in range(3):
            await client.post(
                "/api/v1/entries",
                json={
                    "category_id": sample_category["id"],
                    "entry_date": f"2024-01-{15 + i:02d}",
                    "values": [{"field_id": field_ids[0], "value": str(7 + i)}],
                },
            )

        response = await client.get("/api/v1/entries")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3

    async def test_get_entry_by_id(self, client: AsyncClient, sample_category: dict):
        """Test getting specific entry by ID."""
        field_ids = [f["id"] for f in sample_category["fields"]]

        # Create entry
        create_response = await client.post(
            "/api/v1/entries",
            json={
                "category_id": sample_category["id"],
                "entry_date": "2024-01-15",
                "values": [{"field_id": field_ids[0], "value": "8"}],
            },
        )
        entry_id = create_response.json()["id"]

        # Get entry
        response = await client.get(f"/api/v1/entries/{entry_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == entry_id
        assert data["entry_date"] == "2024-01-15"

    async def test_get_nonexistent_entry(self, client: AsyncClient):
        """Test getting nonexistent entry returns 404."""
        response = await client.get("/api/v1/entries/9999")
        assert response.status_code == 404

    async def test_get_entries_by_category(
        self, client: AsyncClient, sample_category: dict
    ):
        """Test filtering entries by category."""
        field_ids = [f["id"] for f in sample_category["fields"]]

        # Create another category
        other_category = await client.post(
            "/api/v1/categories",
            json={
                "name": "Exercise",
                "fields": [{"name": "Duration", "field_type": "number"}],
            },
        )
        other_category_data = other_category.json()

        # Create entries for both categories
        await client.post(
            "/api/v1/entries",
            json={
                "category_id": sample_category["id"],
                "entry_date": "2024-01-15",
                "values": [{"field_id": field_ids[0], "value": "8"}],
            },
        )
        await client.post(
            "/api/v1/entries",
            json={
                "category_id": other_category_data["id"],
                "entry_date": "2024-01-15",
                "values": [
                    {"field_id": other_category_data["fields"][0]["id"], "value": "30"}
                ],
            },
        )

        # Get only sleep entries
        response = await client.get(
            f"/api/v1/entries?category_id={sample_category['id']}"
        )
        data = response.json()
        assert len(data) == 1
        assert data[0]["category_id"] == sample_category["id"]

    async def test_get_entries_by_date_range(
        self, client: AsyncClient, sample_category: dict
    ):
        """Test filtering entries by date range."""
        field_ids = [f["id"] for f in sample_category["fields"]]

        # Create entries with different dates
        dates = ["2024-01-10", "2024-01-15", "2024-01-20", "2024-01-25"]
        for entry_date in dates:
            await client.post(
                "/api/v1/entries",
                json={
                    "category_id": sample_category["id"],
                    "entry_date": entry_date,
                    "values": [{"field_id": field_ids[0], "value": "8"}],
                },
            )

        # Get entries between Jan 12 and Jan 22
        response = await client.get(
            "/api/v1/entries?start_date=2024-01-12&end_date=2024-01-22"
        )
        data = response.json()
        assert len(data) == 2  # Should get Jan 15 and Jan 20

    async def test_get_entries_by_category_and_date_range(
        self, client: AsyncClient, sample_category: dict
    ):
        """Test using endpoint for category date range."""
        field_ids = [f["id"] for f in sample_category["fields"]]

        # Create entries
        dates = ["2024-01-10", "2024-01-15", "2024-01-20"]
        for entry_date in dates:
            await client.post(
                "/api/v1/entries",
                json={
                    "category_id": sample_category["id"],
                    "entry_date": entry_date,
                    "values": [{"field_id": field_ids[0], "value": "8"}],
                },
            )

        response = await client.get(
            f"/api/v1/entries/category/{sample_category['id']}/range"
            f"?start_date=2024-01-01&end_date=2024-01-31"
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3


@pytest.mark.asyncio
class TestEntrySort:
    """Ordering of `GET /entries` — write order vs event order."""

    async def _create_descending_dates(
        self, client: AsyncClient, category: dict
    ) -> list[int]:
        """
        Three entries written oldest-created first, dated newest-event first.

        Написание в обратном порядке к датам — единственный способ отличить два
        порядка: при совпадающем направлении оба вернули бы одну и ту же выдачу,
        и тест прошёл бы, даже если сортировка не переключилась.
        """
        field_id = category["fields"][0]["id"]
        created_ids = []
        for entry_date in ("2024-01-17", "2024-01-16", "2024-01-15"):
            response = await client.post(
                "/api/v1/entries",
                json={
                    "category_id": category["id"],
                    "entry_date": entry_date,
                    "values": [{"field_id": field_id, "value": "8"}],
                },
            )
            created_ids.append(response.json()["id"])
        return created_ids

    async def test_default_order_is_by_entry_date(
        self, client: AsyncClient, sample_category: dict
    ):
        """Без параметров выдача остаётся прежней: entry_date по убыванию."""
        created_ids = await self._create_descending_dates(client, sample_category)

        response = await client.get("/api/v1/entries")

        assert response.status_code == 200
        assert [e["id"] for e in response.json()] == created_ids

    async def test_sort_by_created_at_returns_last_written_first(
        self, client: AsyncClient, sample_category: dict
    ):
        """`sort=created_at_desc` ставит последнюю сохранённую запись первой."""
        created_ids = await self._create_descending_dates(client, sample_category)

        response = await client.get("/api/v1/entries?sort=created_at_desc")

        assert response.status_code == 200
        assert [e["id"] for e in response.json()] == list(reversed(created_ids))

    async def test_sort_by_created_at_with_limit_one(
        self, client: AsyncClient, sample_category: dict
    ):
        """Лимит поверх сортировки отдаёт ровно последнюю сохранённую запись."""
        created_ids = await self._create_descending_dates(client, sample_category)

        response = await client.get("/api/v1/entries?sort=created_at_desc&limit=1")

        assert response.status_code == 200
        assert [e["id"] for e in response.json()] == [created_ids[-1]]

    async def test_unknown_sort_is_rejected(self, client: AsyncClient):
        """Неизвестное значение сортировки — 422, а не молчаливый фолбэк."""
        response = await client.get("/api/v1/entries?sort=whatever")

        assert response.status_code == 422


@pytest.mark.asyncio
class TestEntryUpdate:
    """Tests for updating entries."""

    async def test_update_entry_notes(self, client: AsyncClient, sample_category: dict):
        """Test updating entry notes."""
        field_ids = [f["id"] for f in sample_category["fields"]]

        # Create entry
        create_response = await client.post(
            "/api/v1/entries",
            json={
                "category_id": sample_category["id"],
                "entry_date": "2024-01-15",
                "notes": "Original notes",
                "values": [{"field_id": field_ids[0], "value": "8"}],
            },
        )
        entry_id = create_response.json()["id"]

        # Update notes
        response = await client.patch(
            f"/api/v1/entries/{entry_id}", json={"notes": "Updated notes"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["notes"] == "Updated notes"

    async def test_update_entry_date(self, client: AsyncClient, sample_category: dict):
        """Test updating entry date."""
        field_ids = [f["id"] for f in sample_category["fields"]]

        # Create entry
        create_response = await client.post(
            "/api/v1/entries",
            json={
                "category_id": sample_category["id"],
                "entry_date": "2024-01-15",
                "values": [{"field_id": field_ids[0], "value": "8"}],
            },
        )
        entry_id = create_response.json()["id"]

        # Update date
        response = await client.patch(
            f"/api/v1/entries/{entry_id}", json={"entry_date": "2024-01-16"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["entry_date"] == "2024-01-16"

    async def test_update_entry_values(
        self, client: AsyncClient, sample_category: dict
    ):
        """Test updating entry field values."""
        field_ids = [f["id"] for f in sample_category["fields"]]

        # Create entry
        create_response = await client.post(
            "/api/v1/entries",
            json={
                "category_id": sample_category["id"],
                "entry_date": "2024-01-15",
                "values": [
                    {"field_id": field_ids[0], "value": "8"},
                    {"field_id": field_ids[1], "value": "excellent"},
                ],
            },
        )
        entry_id = create_response.json()["id"]

        # Update values
        response = await client.patch(
            f"/api/v1/entries/{entry_id}",
            json={
                "values": [
                    {"field_id": field_ids[0], "value": "7"},
                    {"field_id": field_ids[1], "value": "good"},
                ]
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["values"][0]["value"] == "7"
        assert data["values"][1]["value"] == "good"

    async def test_update_nonexistent_entry(self, client: AsyncClient):
        """Test updating nonexistent entry returns 404."""
        response = await client.patch("/api/v1/entries/9999", json={"notes": "Test"})
        assert response.status_code == 404


@pytest.mark.asyncio
class TestEntryDelete:
    """Tests for deleting entries."""

    async def test_delete_entry(self, client: AsyncClient, sample_category: dict):
        """Test deleting an entry."""
        field_ids = [f["id"] for f in sample_category["fields"]]

        # Create entry
        create_response = await client.post(
            "/api/v1/entries",
            json={
                "category_id": sample_category["id"],
                "entry_date": "2024-01-15",
                "values": [{"field_id": field_ids[0], "value": "8"}],
            },
        )
        entry_id = create_response.json()["id"]

        # Delete entry
        response = await client.delete(f"/api/v1/entries/{entry_id}")
        assert response.status_code == 204

        # Verify it's deleted
        get_response = await client.get(f"/api/v1/entries/{entry_id}")
        assert get_response.status_code == 404

    async def test_delete_nonexistent_entry(self, client: AsyncClient):
        """Test deleting nonexistent entry returns 404."""
        response = await client.delete("/api/v1/entries/9999")
        assert response.status_code == 404
