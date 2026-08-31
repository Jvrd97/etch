"""plan_violation

Revision ID: c8f0a2b4d6e7
Revises: b7d9f1a3c5e6
Create Date: 2026-09-01 22:00:00.000000+00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c8f0a2b4d6e7"
down_revision: Union[str, None] = "b7d9f1a3c5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The three vocabularies, written out rather than imported from
# `app.day.constraints`. A migration has to keep meaning what it meant on the day
# it ran: importing application code would let a ninth rule silently rewrite the
# constraint this revision created. The two spellings are expected to agree only
# at this revision.
RULE_CODES = (
    "hard_edges_only",
    "free_evening_empty",
    "work_cap",
    "task_cap",
    "health_before_work",
    "relationship_anchor_required",
    "no_overlap",
    "target_day_only",
)
SEVERITIES = ("block", "warn")
ORIGINS = ("ai", "fallback", "human")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    joined = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({joined})"


def upgrade() -> None:
    op.create_table(
        "plan_violation",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        # No foreign key to `day`: the generator produces violations for dates
        # whose `day` row does not exist yet, and a constraint here would refuse
        # to record the reason the day was never made.
        sa.Column("day_date", sa.Date(), nullable=False),
        sa.Column("plan_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rule_code", sa.String(length=40), nullable=False),
        sa.Column("severity", sa.String(length=8), nullable=False),
        sa.Column("origin", sa.String(length=8), nullable=False),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            _in_list("rule_code", RULE_CODES), name="ck_plan_violation_rule_code"
        ),
        sa.CheckConstraint(
            _in_list("severity", SEVERITIES), name="ck_plan_violation_severity"
        ),
        sa.CheckConstraint(
            _in_list("origin", ORIGINS), name="ck_plan_violation_origin"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_plan_violation_id", "plan_violation", ["id"], unique=False)
    op.create_index(
        "ix_plan_violation_day_date", "plan_violation", ["day_date"], unique=False
    )
    op.create_index(
        "ix_plan_violation_day_rule",
        "plan_violation",
        ["day_date", "rule_code"],
        unique=False,
    )


def downgrade() -> None:
    # Drops what the upgrade made and nothing else. Indexes first, then the
    # table: dropping the table would take them anyway, but naming them keeps
    # the downgrade readable as the exact inverse of the upgrade.
    op.drop_index("ix_plan_violation_day_rule", table_name="plan_violation")
    op.drop_index("ix_plan_violation_day_date", table_name="plan_violation")
    op.drop_index("ix_plan_violation_id", table_name="plan_violation")
    op.drop_table("plan_violation")
