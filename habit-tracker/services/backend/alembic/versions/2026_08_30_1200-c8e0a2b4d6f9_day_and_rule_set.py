"""day and rule set

Revision ID: c8e0a2b4d6f9
Revises: a7c9e1b3d5f8
Create Date: 2026-08-30 12:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c8e0a2b4d6f9"
down_revision: Union[str, None] = "a7c9e1b3d5f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The seed is spelled out here rather than imported from `app.day.rules`: a
# migration must keep meaning what it meant on the day it ran, and importing
# application code would let a later edit rewrite history. The two lists are
# expected to agree only at this revision.
#
# Two rows, because the canon has two versions. `legacy` covers everything
# before 2026-08-17, when the ceiling dropped from ten hours to eight and the
# task bar rose from 80% to all of them; imported history (`#89`) is read
# against it. Everything the record does not name is identical between the rows
# on purpose, so a diff of the two shows exactly what changed and nothing
# invented.
SEED_RULES = [
    {
        "valid_from": "2020-01-01",
        "valid_to": "2026-08-17",
        "timezone": "Europe/Berlin",
        "day_start_hour": 4,
        "work_cap_min": 600,
        "work_hard_cap_min": 600,
        "work_stop_at": "16:00",
        "max_work_tasks": 4,
        "tasks_required_ratio": "0.80",
        "overtime_disqualifies": True,
        "workdays": [1, 2, 3, 4, 5],
        "nocode_days": [2, 4],
        "required_anchors": ["подъём", "спорт", "старт работы", "ревью", "отбой"],
        "note_md": (
            "legacy: канон до 2026-08-17 — потолок 10 ч и планка 80% задач. "
            "Существует ради импортированной истории: её вердикты переносятся "
            "как записаны, а не пересчитываются по нынешним числам."
        ),
    },
    {
        "valid_from": "2026-08-17",
        "valid_to": None,
        "timezone": "Europe/Berlin",
        "day_start_hour": 4,
        "work_cap_min": 480,
        "work_hard_cap_min": 540,
        "work_stop_at": "16:00",
        "max_work_tasks": 4,
        "tasks_required_ratio": "1.00",
        "overtime_disqualifies": True,
        "workdays": [1, 2, 3, 4, 5],
        "nocode_days": [2, 4],
        "required_anchors": ["подъём", "спорт", "старт работы", "ревью", "отбой"],
        "note_md": (
            "Действующий канон по config.md: 8 ч со стопом в 16:00, потолок 9 ч "
            "для исключений, четыре рабочие задачи, закрыты все, переработка "
            "дисквалифицирует день."
        ),
    },
]


def upgrade() -> None:
    rule_set = op.create_table(
        "day_rule_set",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column(
            "timezone",
            sa.String(length=64),
            server_default="Europe/Berlin",
            nullable=False,
        ),
        sa.Column(
            "day_start_hour", sa.SmallInteger(), server_default="4", nullable=False
        ),
        sa.Column(
            "work_cap_min", sa.Integer(), server_default="480", nullable=False
        ),
        sa.Column(
            "work_hard_cap_min", sa.Integer(), server_default="540", nullable=False
        ),
        sa.Column(
            "work_stop_at", sa.Time(), server_default="16:00", nullable=False
        ),
        sa.Column(
            "max_work_tasks", sa.SmallInteger(), server_default="4", nullable=False
        ),
        sa.Column(
            "tasks_required_ratio",
            sa.Numeric(precision=3, scale=2),
            server_default="1.00",
            nullable=False,
        ),
        sa.Column(
            "overtime_disqualifies",
            sa.Boolean(),
            server_default="true",
            nullable=False,
        ),
        # ISO weekday numbers, 1 = Monday .. 7 = Sunday — the numbering
        # `date.isoweekday()` already speaks.
        sa.Column(
            "workdays", postgresql.ARRAY(sa.SmallInteger()), nullable=False
        ),
        sa.Column(
            "nocode_days", postgresql.ARRAY(sa.SmallInteger()), nullable=False
        ),
        sa.Column(
            "required_anchors", postgresql.ARRAY(sa.Text()), nullable=False
        ),
        sa.Column("note_md", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_day_rule_set_id"), "day_rule_set", ["id"])

    # Two rules in force on one date make "which rule applies" a coin toss. The
    # database refuses it, not a service: a service check is skipped by every
    # writer that does not go through it — an import, a later migration, a psql
    # session. Half-open on purpose, so the day a canon changes belongs to the
    # new rule and the two rows share one date instead of two.
    op.execute(
        "ALTER TABLE day_rule_set ADD CONSTRAINT excl_day_rule_set_no_overlap "
        "EXCLUDE USING gist (daterange(valid_from, valid_to, '[)') WITH &&)"
    )

    op.bulk_insert(rule_set, SEED_RULES)

    op.create_table(
        "day",
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("rule_set_id", sa.Integer(), nullable=False),
        # Materialised at creation, never derived on read: the week schedule has
        # already been edited once, and a derived answer would silently re-label
        # every past Tuesday the next time it is.
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("is_nocode", sa.Boolean(), nullable=False),
        # NULL until a human actually opens the day — which is what tells
        # "nobody came" apart from "came and did nothing".
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_touched_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["rule_set_id"], ["day_rule_set.id"]),
        sa.PrimaryKeyConstraint("date"),
        sa.CheckConstraint("kind IN ('work', 'off')", name="ck_day_kind"),
    )
    op.create_index("ix_day_rule_set_id_fk", "day", ["rule_set_id"])


def downgrade() -> None:
    op.drop_index("ix_day_rule_set_id_fk", "day")
    op.drop_table("day")

    op.execute(
        "ALTER TABLE day_rule_set DROP CONSTRAINT excl_day_rule_set_no_overlap"
    )
    op.drop_index(op.f("ix_day_rule_set_id"), "day_rule_set")
    op.drop_table("day_rule_set")
