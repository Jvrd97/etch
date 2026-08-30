"""anchor_kind, day_anchor, training_day, training_state, body_complaint, personal_record

Revision ID: e6b8d0f2a4c7
Revises: d5a7c9e1f3b6
Create Date: 2026-09-01 16:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "e6b8d0f2a4c7"
down_revision: Union[str, None] = "d5a7c9e1f3b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The catalogue is seeded from the canon that is already in the table rather
# than from a list retyped here: `required_anchors` of the rule in force is
# where the five edges of the day live, and a second spelling of them in a
# migration is the copy that drifts. `WITH ORDINALITY` keeps the order the rule
# wrote them in.
SEED_FROM_RULE = """
INSERT INTO anchor_kind (code, title, ord, counts_for_verdict,
                         required_in_nonwork_evening)
SELECT anchor.code, anchor.code, anchor.ord::smallint, true, false
FROM (
    SELECT code, ord
    FROM day_rule_set,
         LATERAL unnest(day_rule_set.required_anchors) WITH ORDINALITY AS a(code, ord)
    WHERE day_rule_set.valid_to IS NULL
) AS anchor
ON CONFLICT (code) DO NOTHING
"""

# «Вечер с близкими» — третий приоритет `config.md`, у которого до `#92` не было
# ни якоря, ни колонки, ни проверки. Он единственный со признаком «требуется в
# нерабочий вечер»: само правило `relationship_anchor_required` живёт в `#142`,
# здесь заводится вид якоря и его признак. `ord` считается от того, сколько
# краёв дня уже назвал канон, — шестым при пяти, седьмым при шести.
SEED_RELATIONSHIP = """
INSERT INTO anchor_kind (code, title, ord, counts_for_verdict,
                         required_in_nonwork_evening)
SELECT 'relationship', 'вечер с близкими',
       (COALESCE(MAX(ord), 0) + 1)::smallint, true, true
FROM anchor_kind
ON CONFLICT (code) DO NOTHING
"""

# Пустая база — миграция бежит раньше, чем в `day_rule_set` появится строка (её
# кладёт ревизия `c8e0a2b4d6f9`, но чужой снимок мог её не донести). Тогда
# каталог остаётся пустым, и приложение засевает его само —
# `app.crud.day.seed_rules` вызывает `seed_anchor_kinds`. Отдельного списка
# видов в миграции нет намеренно: он был бы третьей копией.


def upgrade() -> None:
    op.create_table(
        "anchor_kind",
        # The code is the key: a kind of anchor is a word the rule row names, and
        # a surrogate id would put a join between the canon and its vocabulary.
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("ord", sa.SmallInteger(), nullable=False),
        sa.Column(
            "counts_for_verdict", sa.Boolean(), server_default="true", nullable=False
        ),
        sa.Column(
            "required_in_nonwork_evening",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("code"),
    )

    op.create_table(
        "day_anchor",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("day_date", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        # The line of the plan the anchor is written on, when there is one. A
        # plan rewritten at 14:00 must not take the tick off an anchor, hence
        # SET NULL rather than CASCADE.
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=True),
        # NULL is «ещё ничего не сказано» — a different fact from «не сделал»,
        # and the one the anchor of the third priority lived in until now.
        sa.Column("state", sa.String(length=16), nullable=True),
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
        sa.ForeignKeyConstraint(["day_date"], ["day.date"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["kind"], ["anchor_kind.code"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["item_id"], ["plan_item.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        # «Два подъёма 30-го» — не состояние, в котором можно оказаться. В базе,
        # а не в сервисе: проверку сервиса обходит импорт, миграция и psql.
        sa.UniqueConstraint("day_date", "kind", name="uq_day_anchor_day_kind"),
        sa.CheckConstraint(
            "state IS NULL OR state IN ('done', 'failed', 'skipped')",
            name="ck_day_anchor_state",
        ),
    )
    op.create_index("ix_day_anchor_kind", "day_anchor", ["kind"])

    op.execute(SEED_FROM_RULE)
    op.execute(SEED_RELATIONSHIP)

    op.create_table(
        "training_day",
        sa.Column("day_date", sa.Date(), nullable=False),
        # What the day trained, and which of it was heavy. Two arrays because
        # the 48-hour gate is about heaviness: «один подход подтягиваний» is a
        # pull day that must not block tomorrow's pull day.
        sa.Column(
            "patterns",
            postgresql.ARRAY(sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "heavy_patterns",
            postgresql.ARRAY(sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("planned_md", sa.Text(), nullable=True),
        sa.Column("done_md", sa.Text(), nullable=True),
        sa.Column("skipped", sa.Boolean(), server_default="false", nullable=False),
        # NULL is «не отмечено», not «не было»: the outdoor line is the one that
        # was silently eaten by the strength block twice in one week.
        sa.Column("outdoor_done", sa.Boolean(), nullable=True),
        sa.Column("near_failure", sa.Boolean(), server_default="false", nullable=False),
        # The dated paragraph of `training/state.md`: the only record of *why* a
        # day went the way it did, and not derivable from the patterns beside it.
        sa.Column("note_md", sa.Text(), nullable=True),
        sa.Column("minimum_md", sa.Text(), nullable=True),
        # The minimum's own tick. 29 August is why the column exists.
        sa.Column("minimum_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "sets", postgresql.JSONB(), server_default="{}", nullable=False
        ),
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
        sa.ForeignKeyConstraint(["day_date"], ["day.date"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["minimum_item_id"], ["plan_item.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("day_date"),
    )

    op.create_table(
        "training_state",
        # One person, one body, one state. A second row would be a second answer
        # to «когда была последняя тяжёлая тяга».
        sa.Column("id", sa.SmallInteger(), nullable=False),
        sa.Column("last_heavy_pull", sa.Date(), nullable=True),
        sa.Column("last_heavy_push", sa.Date(), nullable=True),
        sa.Column("last_legs", sa.Date(), nullable=True),
        sa.Column("last_run", sa.Date(), nullable=True),
        sa.Column("last_outdoor", sa.Date(), nullable=True),
        sa.Column("last_cardio", sa.Date(), nullable=True),
        sa.Column(
            "near_failure_days",
            postgresql.ARRAY(sa.Date()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "week_sets", postgresql.JSONB(), server_default="{}", nullable=False
        ),
        # The single authored column: «объём 4x6-8 RIR 1-2» is a decision about
        # the next four weeks, not a number derivable from what happened.
        sa.Column(
            "progression_stage",
            postgresql.JSONB(),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("skipped_days", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "recomputed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("id = 1", name="ck_training_state_singleton"),
    )

    op.create_table(
        "body_complaint",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("opened_on", sa.Date(), nullable=False),
        # A symptom for a gate, never a medical record: no diagnosis, no
        # prescription, no test result lands here (ADR-0014, «Не хранится»).
        sa.Column("area", sa.Text(), nullable=False),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column("severity", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("closed_on", sa.Date(), nullable=True),
        sa.Column("closed_reason", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('open', 'closed')", name="ck_body_complaint_status"
        ),
        sa.CheckConstraint(
            "status <> 'closed' OR closed_on IS NOT NULL",
            name="ck_body_complaint_closed_has_date",
        ),
    )
    op.create_index("ix_body_complaint_status", "body_complaint", ["status"])

    op.create_table(
        "personal_record",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exercise", sa.Text(), nullable=False),
        sa.Column("variant", sa.Text(), nullable=True),
        # «9/10/5/3» is both the record and the diagnosis — the first set to
        # failure ate the other three — so the sets are text and the single
        # number sits beside them, nullable.
        sa.Column("sets", sa.Text(), nullable=True),
        sa.Column("best_plain", sa.Integer(), nullable=True),
        sa.Column("achieved_on", sa.Date(), nullable=False),
        sa.Column("target", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_personal_record_exercise", "personal_record", ["exercise"])


def downgrade() -> None:
    # Reverse order of creation: `day_anchor` references `anchor_kind`, and both
    # training tables reference `day` and `plan_item` rather than each other.
    op.drop_index("ix_personal_record_exercise", table_name="personal_record")
    op.drop_table("personal_record")
    op.drop_index("ix_body_complaint_status", table_name="body_complaint")
    op.drop_table("body_complaint")
    op.drop_table("training_state")
    op.drop_table("training_day")
    op.drop_index("ix_day_anchor_kind", table_name="day_anchor")
    op.drop_table("day_anchor")
    op.drop_table("anchor_kind")
