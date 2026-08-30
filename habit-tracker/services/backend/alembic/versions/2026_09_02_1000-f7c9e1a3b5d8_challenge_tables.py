"""challenges and challenge_days — an obligation with a verdict on every day

Revision ID: f7c9e1a3b5d8
Revises: e6b8d0f2a4c7
Create Date: 2026-09-02 10:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f7c9e1a3b5d8"
down_revision: Union[str, None] = "e6b8d0f2a4c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "challenges",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        # RESTRICT on both: an obligation is history, and deleting the category
        # it was about must be refused rather than take the history with it.
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("field_id", sa.Integer(), nullable=False),
        sa.Column("rule_kind", sa.String(length=20), nullable=False),
        # NULL for `checked` and `abstain`: they have nothing to compare with.
        sa.Column("target", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column(
            "failure_mode", sa.String(length=10), server_default="any_miss", nullable=False
        ),
        sa.Column(
            "allowed_misses", sa.SmallInteger(), server_default="0", nullable=False
        ),
        sa.Column(
            "status", sa.String(length=12), server_default="active", nullable=False
        ),
        sa.Column("failed_on", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["field_id"], ["fields.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("ends_on >= starts_on", name="ck_challenge_window"),
        sa.CheckConstraint("allowed_misses >= 0", name="ck_challenge_allowed_misses"),
        sa.CheckConstraint(
            "rule_kind IN ('metric_at_least', 'metric_at_most', 'checked', 'abstain')",
            name="ck_challenge_rule_kind",
        ),
        sa.CheckConstraint(
            "failure_mode IN ('any_miss', 'budget')", name="ck_challenge_failure_mode"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'won', 'failed', 'abandoned')",
            name="ck_challenge_status",
        ),
    )
    op.create_index("ix_challenges_id", "challenges", ["id"])
    op.create_index("ix_challenges_category_id", "challenges", ["category_id"])
    op.create_index("ix_challenges_field_id", "challenges", ["field_id"])
    # The read path of the list: the active obligations whose window is open.
    op.create_index("ix_challenges_status_ends", "challenges", ["status", "ends_on"])

    op.create_table(
        "challenge_days",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("challenge_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("verdict", sa.String(length=10), nullable=False),
        # `manual` is a person's word and re-materialization never overwrites it.
        sa.Column(
            "source", sa.String(length=10), server_default="computed", nullable=False
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["challenge_id"], ["challenges.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        # The natural key the lazy materialization upserts on: this is what makes
        # two `recompute` calls leave the same number of rows.
        sa.UniqueConstraint("challenge_id", "day", name="uq_challenge_day"),
        sa.CheckConstraint(
            "verdict IN ('done', 'miss', 'pending')", name="ck_challenge_day_verdict"
        ),
        sa.CheckConstraint(
            "source IN ('computed', 'manual')", name="ck_challenge_day_source"
        ),
    )
    op.create_index("ix_challenge_days_id", "challenge_days", ["id"])
    op.create_index("ix_challenge_days_challenge_id", "challenge_days", ["challenge_id"])
    op.create_index("ix_challenge_days_day", "challenge_days", ["day"])


def downgrade() -> None:
    op.drop_index("ix_challenge_days_day", "challenge_days")
    op.drop_index("ix_challenge_days_challenge_id", "challenge_days")
    op.drop_index("ix_challenge_days_id", "challenge_days")
    op.drop_table("challenge_days")

    op.drop_index("ix_challenges_status_ends", "challenges")
    op.drop_index("ix_challenges_field_id", "challenges")
    op.drop_index("ix_challenges_category_id", "challenges")
    op.drop_index("ix_challenges_id", "challenges")
    op.drop_table("challenges")
