"""day_rule_set generator columns

Revision ID: d5a7c9e1f3b6
Revises: c4f6b8d0e2a5
Create Date: 2026-09-01 14:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "d5a7c9e1f3b6"
down_revision: Union[str, None] = "c4f6b8d0e2a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The map of the day, as `config.md` writes it. Spelled out here rather than
# imported from `app.day.rules`: a migration has to keep meaning what it meant
# on the day it ran, and importing application code would let a later edit
# rewrite history. The two spellings are expected to agree only at this
# revision.
#
# `07:45` is the start of work the prose names ("Старт 7:45, стоп 16:00,
# жёстко"), not the `7:30-8:00` of the table above it; `15:40` is review; `22:30`
# is the ceiling of bedtime, not a target.
#
# The free evening is `19:10-21:00` — from the end of dinner to the hour screens
# go off. That is the block `config.md` calls «последние 2-3 ч — свободный блок,
# награда, а не обязанность», and the one the generator may put nothing into.
#
# The evening with the family, `18:30-21:00`, is *not* in `config.md`: the third
# priority («здоровье > работа > отношения») has never been written as hours.
# This is its first recorded version — dinner to screens-off — and, like every
# other number here, it changes by a new row rather than by an edit of code.
WAKE_AT = "06:00"
WORK_START = "07:45"
REVIEW_AT = "15:40"
BEDTIME_MAX = "22:30"
FREE_EVENING = ("19:10", "21:00")
RELATIONSHIP_EVENING = ("18:30", "21:00")

# Ceilings the generator obeys. `overtime_lost_min` is the wall past which a day
# is never *planned*, whatever the exception ceiling allows: 600 minutes, the ten
# hours `config.md` struck out in the entry of 2026-08-17 ("десять часов
# оказались не потолком, а нормой"). `max_study_items` — два учебных пункта:
# слот А и «пишу сам, без ИИ».
OVERTIME_LOST_MIN = 600
MAX_STUDY_ITEMS = 2

# Which kinds of plan item may declare themselves immovable. Item kinds, not
# anchor kinds: ADR-0015 illustrates the list with «подъём, спорт, старт работы,
# ревью, отбой», but those five are already `required_anchors`, and the decision
# of 2026-08-30 is that `rigidity='hard'` is allowed to every `hard_point` —
# встреча в 11:00 жёсткая по определению своего вида.
HARD_EDGE_KINDS = '["anchor", "hard_point"]'

# The verdict formula as data: which conditions lower a day, in the order they
# are weighed. `not_closed` is deliberately absent — «никто не закрыл день» is
# the absence of a judgement, not a condition of one.
VERDICT_RULE = '{"reason_order": ["overtime", "anchors", "tasks"]}'

# The composition of anchors. The current row gains `relationship` — «вечер с
# близкими» — so that the third priority of `config.md` weighs on the verdict
# the way health and work already do (`#92` заводит вид якоря, `#147` проверяет
# его при планировании). The legacy row keeps the five it was lived under: a day
# of July is not judged by a rule written in September.
ANCHORS_LEGACY = '["подъём", "спорт", "старт работы", "ревью", "отбой"]'
ANCHORS_CURRENT = (
    '["подъём", "спорт", "старт работы", "ревью", "отбой", "relationship"]'
)

# Выходные — не дополнение к `workdays`, а свой список: в выходной канон кладёт
# учёбу, уроки и музыку, а «не рабочий день» не говорит про день ничего.
# Числа согласованы с `workdays` строки (пн-пт), а не с недельным расписанием
# `config.md` от 2026-08-17 (рабочие пн, вт, ср, пт, сб; выходные чт и вс):
# `workdays` этой ревизией не трогается, чтобы вид уже созданных дней не поехал,
# и приводится в порядок отдельной строкой канона (`#152`).
DAYS_OFF = "[6, 7]"

CANON_CHANGED_ON = "2026-08-17"

# Columns added here, in the order they are dropped by `downgrade`.
ADDED_COLUMNS = (
    "overtime_lost_min",
    "max_study_items",
    "wake_at",
    "work_start",
    "review_at",
    "bedtime_max",
    "free_evening_start",
    "free_evening_end",
    "relationship_anchor_required",
    "relationship_evening_start",
    "relationship_evening_end",
    "hard_edge_kinds",
    "anchors",
    "verdict_rule",
    "days_off",
)


def upgrade() -> None:
    # Every column arrives NOT NULL with a server default, so the two rows
    # already in the table get a canon rather than a NULL, and any writer that
    # does not go through the service — an import, a psql session — still gets a
    # complete rule row.
    op.add_column(
        "day_rule_set",
        sa.Column(
            "overtime_lost_min",
            sa.Integer(),
            server_default=str(OVERTIME_LOST_MIN),
            nullable=False,
        ),
    )
    op.add_column(
        "day_rule_set",
        sa.Column(
            "max_study_items",
            sa.SmallInteger(),
            server_default=str(MAX_STUDY_ITEMS),
            nullable=False,
        ),
    )
    for name, default in (
        ("wake_at", WAKE_AT),
        ("work_start", WORK_START),
        ("review_at", REVIEW_AT),
        ("bedtime_max", BEDTIME_MAX),
        ("free_evening_start", FREE_EVENING[0]),
        ("free_evening_end", FREE_EVENING[1]),
        ("relationship_evening_start", RELATIONSHIP_EVENING[0]),
        ("relationship_evening_end", RELATIONSHIP_EVENING[1]),
    ):
        op.add_column(
            "day_rule_set",
            sa.Column(name, sa.Time(), server_default=default, nullable=False),
        )
    op.add_column(
        "day_rule_set",
        sa.Column(
            "relationship_anchor_required",
            sa.Boolean(),
            server_default="true",
            nullable=False,
        ),
    )
    for name, default in (
        ("hard_edge_kinds", HARD_EDGE_KINDS),
        ("anchors", ANCHORS_CURRENT),
        ("verdict_rule", VERDICT_RULE),
        ("days_off", DAYS_OFF),
    ):
        op.add_column(
            "day_rule_set",
            sa.Column(
                name,
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text(f"'{default}'::jsonb"),
                nullable=False,
            ),
        )

    # The legacy row differs from the current one only in what the record names.
    # Вечер с близкими стал требованием канона вместе с этой ревизией, поэтому
    # день, прожитый до 2026-08-17, им не судится — иначе смена канона задним
    # числом переписала бы вердикты, ради чего таблица и версионируется.
    op.execute(
        sa.text(
            "UPDATE day_rule_set SET anchors = CAST(:anchors AS jsonb), "
            "relationship_anchor_required = false "
            "WHERE valid_from < CAST(:changed_on AS date)"
        ).bindparams(anchors=ANCHORS_LEGACY, changed_on=CANON_CHANGED_ON)
    )


def downgrade() -> None:
    for name in reversed(ADDED_COLUMNS):
        op.drop_column("day_rule_set", name)
