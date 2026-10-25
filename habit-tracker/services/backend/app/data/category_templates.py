# [review:need-review] PHASE-01/178-builtin-category-templates
# summary: code catalog of built-in category templates (Supplements, Water, Sleep, Weight)
"""The catalog lives in code, not in the database: it ships with the release and
a template becomes a real, ordinary category only when the user applies it."""

from app.schemas.category import FieldCreate
from app.schemas.category_template import CategoryTemplate

HEALTH_GROUP = "Health"

CATEGORY_TEMPLATES: tuple[CategoryTemplate, ...] = (
    CategoryTemplate(
        key="supplements",
        name="Supplements",
        description="Tick off the supplements you took today.",
        color="#F59E0B",
        display_mode="checklist",
        group=HEALTH_GROUP,
        fields=[
            FieldCreate(name="Vitamin D", field_type="boolean", order=1),
            FieldCreate(name="Omega-3", field_type="boolean", order=2),
            FieldCreate(name="Magnesium", field_type="boolean", order=3),
        ],
    ),
    CategoryTemplate(
        key="water",
        name="Water",
        description="Water you drink during the day.",
        color="#3B82F6",
        group=HEALTH_GROUP,
        fields=[
            FieldCreate(
                name="Volume",
                field_type="number",
                order=1,
                unit="ml",
                quick_steps=[-250, 250, 500],
            ),
        ],
    ),
    CategoryTemplate(
        key="sleep",
        name="Sleep",
        description="How long you slept.",
        color="#8B5CF6",
        group=HEALTH_GROUP,
        fields=[
            FieldCreate(
                name="Hours",
                field_type="number",
                order=1,
                unit="h",
                quick_steps=[-0.5, 0.5, 1],
            ),
        ],
    ),
    CategoryTemplate(
        key="weight",
        name="Weight",
        description="Body weight over time.",
        color="#10B981",
        group=HEALTH_GROUP,
        fields=[
            FieldCreate(
                name="Weight",
                field_type="number",
                order=1,
                unit="kg",
                quick_steps=[-0.1, 0.1],
            ),
        ],
    ),
)
