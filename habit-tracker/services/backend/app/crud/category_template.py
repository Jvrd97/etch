# [review:need-review] PHASE-01/178-builtin-category-templates
# summary: list the template catalog with an `added` flag and apply picked templates through apply_category_batch, skipping names that already exist
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.category import apply_category_batch
from app.data.category_templates import CATEGORY_TEMPLATES
from app.models import Category
from app.schemas.category import BatchCreateCategoryOp, CategoryBatchRequest
from app.schemas.category_template import (
    CategoryTemplate,
    CategoryTemplateApplyResponse,
    CategoryTemplateResponse,
)

_TEMPLATES_BY_KEY: dict[str, CategoryTemplate] = {
    template.key: template for template in CATEGORY_TEMPLATES
}


class UnknownTemplateError(ValueError):
    """The request names keys that are not in the catalog."""

    def __init__(self, keys: list[str]) -> None:
        super().__init__(f"Unknown category template: {', '.join(keys)}")


async def _existing_names(
    db: AsyncSession, templates: list[CategoryTemplate]
) -> set[str]:
    """Names of the given templates that already belong to a category (one query)."""
    result = await db.execute(
        select(Category.name).where(Category.name.in_([t.name for t in templates]))
    )
    return set(result.scalars().all())


async def list_templates(db: AsyncSession) -> list[CategoryTemplateResponse]:
    """The whole catalog, each item flagged by whether its category exists."""
    existing = await _existing_names(db, list(CATEGORY_TEMPLATES))
    return [
        CategoryTemplateResponse(
            **template.model_dump(), added=template.name in existing
        )
        for template in CATEGORY_TEMPLATES
    ]


async def apply_templates(
    db: AsyncSession, keys: list[str]
) -> CategoryTemplateApplyResponse:
    """Create the picked templates as ordinary categories in one transaction.

    A template whose name is already taken is skipped, not overwritten: the
    existing category may be the user's own and is left exactly as it was.
    Unknown keys reject the whole request before anything is written.
    """
    unknown = [key for key in dict.fromkeys(keys) if key not in _TEMPLATES_BY_KEY]
    if unknown:
        raise UnknownTemplateError(unknown)

    picked = [_TEMPLATES_BY_KEY[key] for key in dict.fromkeys(keys)]
    existing = await _existing_names(db, picked)
    to_create = [template for template in picked if template.name not in existing]
    skipped = [template.key for template in picked if template.name in existing]

    if not to_create:
        return CategoryTemplateApplyResponse(skipped=skipped)

    created = await apply_category_batch(
        db,
        CategoryBatchRequest(
            operations=[
                BatchCreateCategoryOp(**template.model_dump(exclude={"key"}))
                for template in to_create
            ]
        ),
    )
    return CategoryTemplateApplyResponse(categories=created.categories, skipped=skipped)
