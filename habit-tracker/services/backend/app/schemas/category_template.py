# [review:need-review] PHASE-01/178-builtin-category-templates
# summary: built-in category template, its listing item and the apply request/response
from pydantic import BaseModel, Field

from app.schemas.category import CategoryBase, CategoryResponse, FieldCreate

TEMPLATE_KEY_MAX_LENGTH = 50


class CategoryTemplate(CategoryBase):
    """A category the app can pre-fill: same shape a hand-made one would have.

    `key` is the stable handle the client sends back; the name is user-facing and
    becomes the category name, so it is not usable as an identifier.
    """

    key: str = Field(..., min_length=1, max_length=TEMPLATE_KEY_MAX_LENGTH)
    fields: list[FieldCreate] = Field(default_factory=list)


class CategoryTemplateResponse(CategoryTemplate):
    """Catalog item plus whether a category with this name already exists."""

    added: bool


class CategoryTemplateApplyRequest(BaseModel):
    """Keys of the templates the user picked."""

    keys: list[str] = Field(..., min_length=1)


class CategoryTemplateApplyResponse(BaseModel):
    """What the apply created, and which picked templates were already present."""

    categories: list[CategoryResponse] = []
    skipped: list[str] = []
