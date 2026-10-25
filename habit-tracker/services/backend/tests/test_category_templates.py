"""
Built-in category templates: a code catalog applied through the batch machinery.

A template is an ordinary category that merely starts life pre-filled, so every
assertion about the result goes through the regular category endpoints.
"""

# [review:need-review] PHASE-01/178-builtin-category-templates
# summary: catalog invariants, GET /categories/templates, POST /categories/templates/apply (atomic, idempotent, nothing created unprompted)
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.crud.category import CHECKLIST_DISPLAY_MODE, checklist_has_boolean_field
from app.data.category_templates import CATEGORY_TEMPLATES

TEMPLATES_URL = "/api/v1/categories/templates"
APPLY_URL = "/api/v1/categories/templates/apply"
SUPPLEMENTS_KEY = "supplements"


async def _apply(client: AsyncClient, keys: list[str]) -> Any:
    return await client.post(APPLY_URL, json={"keys": keys})


async def _all_categories(client: AsyncClient) -> list[dict[str, Any]]:
    response = await client.get("/api/v1/categories", params={"active_only": False})
    assert response.status_code == 200
    return list(response.json())


@contextmanager
def _recorded_statements(db: AsyncSession) -> Iterator[list[str]]:
    statements: list[str] = []

    def record(
        _conn: Connection, _cursor: object, statement: str, *_args: object
    ) -> None:
        statements.append(statement)

    assert isinstance(db.bind, AsyncEngine)
    engine = db.bind.sync_engine
    event.listen(engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", record)


class TestCatalog:
    def test_it_includes_supplements(self) -> None:
        assert SUPPLEMENTS_KEY in {template.key for template in CATEGORY_TEMPLATES}

    def test_keys_and_names_are_unique(self) -> None:
        keys = [template.key for template in CATEGORY_TEMPLATES]
        names = [template.name for template in CATEGORY_TEMPLATES]
        assert len(set(keys)) == len(keys)
        assert len(set(names)) == len(names)

    @pytest.mark.parametrize("template", CATEGORY_TEMPLATES, ids=lambda t: t.key)
    def test_every_template_is_a_valid_category(self, template: Any) -> None:
        assert template.fields, "a template without fields is an empty screen"
        if template.display_mode == CHECKLIST_DISPLAY_MODE:
            assert checklist_has_boolean_field(
                [field.field_type for field in template.fields]
            )


class TestListTemplates:
    async def test_lists_the_catalog_and_marks_nothing_as_added(
        self, client: AsyncClient
    ) -> None:
        response = await client.get(TEMPLATES_URL)

        assert response.status_code == 200
        body = response.json()
        assert [item["key"] for item in body] == [t.key for t in CATEGORY_TEMPLATES]
        assert all(item["added"] is False for item in body)

    async def test_listing_creates_nothing(self, client: AsyncClient) -> None:
        await client.get(TEMPLATES_URL)

        assert await _all_categories(client) == []

    async def test_marks_a_template_whose_category_already_exists(
        self, client: AsyncClient
    ) -> None:
        assert (await _apply(client, [SUPPLEMENTS_KEY])).status_code == 201

        body = (await client.get(TEMPLATES_URL)).json()

        added = {item["key"]: item["added"] for item in body}
        assert added[SUPPLEMENTS_KEY] is True
        assert [key for key, flag in added.items() if not flag] == [
            t.key for t in CATEGORY_TEMPLATES if t.key != SUPPLEMENTS_KEY
        ]

    async def test_statements_do_not_grow_with_the_added_templates(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        with _recorded_statements(db_session) as none_added:
            await client.get(TEMPLATES_URL)
        await _apply(client, [template.key for template in CATEGORY_TEMPLATES])

        with _recorded_statements(db_session) as all_added:
            await client.get(TEMPLATES_URL)

        assert len(all_added) == len(none_added)


class TestApplyTemplates:
    async def test_creates_an_ordinary_category_with_its_fields(
        self, client: AsyncClient
    ) -> None:
        response = await _apply(client, [SUPPLEMENTS_KEY])

        assert response.status_code == 201
        body = response.json()
        assert body["skipped"] == []
        [created] = body["categories"]
        template = next(t for t in CATEGORY_TEMPLATES if t.key == SUPPLEMENTS_KEY)
        assert created["name"] == template.name
        assert created["display_mode"] == template.display_mode
        assert [f["name"] for f in created["fields"]] == [
            f.name for f in template.fields
        ]
        # The same category is reachable through the regular endpoint.
        stored = await client.get(f"/api/v1/categories/{created['id']}")
        assert stored.status_code == 200
        assert stored.json()["fields"] == created["fields"]

    async def test_applies_several_templates_in_one_call(
        self, client: AsyncClient
    ) -> None:
        keys = [template.key for template in CATEGORY_TEMPLATES]

        response = await _apply(client, keys)

        assert response.status_code == 201
        assert [c["name"] for c in response.json()["categories"]] == [
            t.name for t in CATEGORY_TEMPLATES
        ]
        assert len(await _all_categories(client)) == len(CATEGORY_TEMPLATES)

    async def test_applying_twice_creates_no_duplicate(
        self, client: AsyncClient
    ) -> None:
        await _apply(client, [SUPPLEMENTS_KEY])

        again = await _apply(client, [SUPPLEMENTS_KEY])

        assert again.status_code == 201
        assert again.json() == {"categories": [], "skipped": [SUPPLEMENTS_KEY]}
        names = [c["name"] for c in await _all_categories(client)]
        assert (
            names.count(
                next(t.name for t in CATEGORY_TEMPLATES if t.key == SUPPLEMENTS_KEY)
            )
            == 1
        )

    async def test_a_repeated_key_in_one_request_is_created_once(
        self, client: AsyncClient
    ) -> None:
        response = await _apply(client, [SUPPLEMENTS_KEY, SUPPLEMENTS_KEY])

        assert response.status_code == 201
        assert len(response.json()["categories"]) == 1
        assert len(await _all_categories(client)) == 1

    async def test_an_existing_category_is_skipped_and_the_rest_still_land(
        self, client: AsyncClient
    ) -> None:
        template = next(t for t in CATEGORY_TEMPLATES if t.key == SUPPLEMENTS_KEY)
        other = next(t for t in CATEGORY_TEMPLATES if t.key != SUPPLEMENTS_KEY)
        own = await client.post(
            "/api/v1/categories", json={"name": template.name, "fields": []}
        )
        assert own.status_code == 201

        response = await _apply(client, [SUPPLEMENTS_KEY, other.key])

        assert response.status_code == 201
        body = response.json()
        assert body["skipped"] == [SUPPLEMENTS_KEY]
        assert [c["name"] for c in body["categories"]] == [other.name]
        # The user's own category is left exactly as it was.
        stored = await client.get(f"/api/v1/categories/{own.json()['id']}")
        assert stored.json()["fields"] == []

    async def test_an_unknown_key_is_rejected_and_nothing_is_created(
        self, client: AsyncClient
    ) -> None:
        response = await _apply(client, [SUPPLEMENTS_KEY, "no-such-template"])

        assert response.status_code == 422
        assert "no-such-template" in response.json()["detail"]
        assert await _all_categories(client) == []

    async def test_an_empty_selection_is_rejected(self, client: AsyncClient) -> None:
        response = await _apply(client, [])

        assert response.status_code == 422

    async def test_a_template_category_can_be_renamed_extended_and_deleted(
        self, client: AsyncClient
    ) -> None:
        [created] = (await _apply(client, [SUPPLEMENTS_KEY])).json()["categories"]
        category_id = created["id"]

        renamed = await client.patch(
            f"/api/v1/categories/{category_id}", json={"name": "Мои добавки"}
        )
        assert renamed.status_code == 200
        assert renamed.json()["name"] == "Мои добавки"

        fields = [
            {"id": f["id"], "name": f["name"], "field_type": f["field_type"]}
            for f in created["fields"]
        ] + [{"name": "Zinc", "field_type": "boolean"}]
        extended = await client.patch(
            f"/api/v1/categories/{category_id}", json={"fields": fields}
        )
        assert extended.status_code == 200
        assert len(extended.json()["fields"]) == len(created["fields"]) + 1

        assert (
            await client.delete(f"/api/v1/categories/{category_id}")
        ).status_code == 204
