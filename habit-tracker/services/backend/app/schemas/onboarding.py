# [review:need-review] PHASE-01/52-text-to-category-plan
# summary: additive-only onboarding plan DTOs (create_category / add_field) + draft request
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.category import (
    CategoryDisplayMode,
    CategoryStreakMode,
    COLOR_PATTERN,
)


class PlanField(BaseModel):
    """A field the plan proposes for a category."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=100)
    field_type: str = Field(
        ...,
        description=(
            "One of: text, number, boolean, date, datetime, time, select, duration"
        ),
    )
    is_required: bool = False
    options: str | None = None
    order: int = 0


class CreateCategoryOp(BaseModel):
    """Create a brand-new category with its fields."""

    model_config = ConfigDict(extra="forbid")

    op: Literal["create_category"] = "create_category"
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    icon: str | None = Field(None, max_length=50)
    color: str | None = Field(None, max_length=7, pattern=COLOR_PATTERN)
    display_mode: CategoryDisplayMode = "form"
    streak_mode: CategoryStreakMode = "build"
    group: str | None = Field(None, max_length=100)
    fields: list[PlanField] = Field(default_factory=list)
    # Response-only: set by the server when `name` collides with an existing
    # category (Category.name is globally unique). The model never sends it.
    name_conflict: bool = False


class AddFieldOp(BaseModel):
    """Add a new field to an existing category."""

    model_config = ConfigDict(extra="forbid")

    op: Literal["add_field"] = "add_field"
    category_id: int
    field: PlanField


PlanOperation = Annotated[
    Union[CreateCategoryOp, AddFieldOp], Field(discriminator="op")
]


class OnboardingPlan(BaseModel):
    """
    Additive-only plan: only create_category and add_field are expressible.

    Deletion, rename, type change and deactivation have no representation here
    on purpose — the plan can never instruct a destructive diff-sync.
    """

    operations: list[PlanOperation] = Field(default_factory=list)


class OnboardingDraftRequest(BaseModel):
    """Free-text description of what the user wants to track."""

    transcript: str = Field(..., min_length=1)
