# [review:need-review] PHASE-03/92
# summary: the anchor tables — `anchor_kind` as a catalogue of rows (string keys, not an enum, by the precedent of health_metrics) and `day_anchor`, which ties one anchor of one day to the line of the plan it lives on and refuses a second anchor of the same kind on the same date
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date as date_type
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base

__all__ = [
    "ANCHOR_KIND_SEED",
    "ANCHOR_RELATIONSHIP",
    "ANCHOR_STATES",
    "ANCHOR_STATE_DONE",
    "ANCHOR_STATE_FAILED",
    "ANCHOR_STATE_SKIPPED",
    "CLOSING_ANCHOR_STATES",
    "DEFAULT_ANCHOR_CODES",
    "LEGACY_ANCHOR_CODES",
    "AnchorKind",
    "AnchorKindSeed",
    "DayAnchor",
]

# What an anchor of a day can say about itself. The same three words a
# `plan_mark` uses, and for the same reason: «отложил» is a judgement about the
# canon of that day, not about the work, and it must not be reachable by
# clicking twice.
ANCHOR_STATE_DONE = "done"
ANCHOR_STATE_FAILED = "failed"
ANCHOR_STATE_SKIPPED = "skipped"
ANCHOR_STATES: tuple[str, ...] = (
    ANCHOR_STATE_DONE,
    ANCHOR_STATE_FAILED,
    ANCHOR_STATE_SKIPPED,
)

# The states under which an anchor does not lower the day. `skipped` counts as
# closed exactly as it does for a task: an anchor that stopped being relevant is
# not one the day missed.
CLOSING_ANCHOR_STATES: frozenset[str] = frozenset(
    {ANCHOR_STATE_DONE, ANCHOR_STATE_SKIPPED}
)

# The code of the third priority of `config.md`. Named because two other modules
# have to say it out loud — the seed of the legacy rule, which does not include
# it, and the import, which has no anchor of relationships in its files.
ANCHOR_RELATIONSHIP = "relationship"


@dataclass(frozen=True)
class AnchorKindSeed:
    """
    One row of the catalogue as a fresh installation starts with it.

    A record rather than a tuple so that the migration, `app.crud.anchor` and
    the tests compare field by field, and so that adding a seventh anchor is a
    line here plus an INSERT rather than an edit of anything that judges a day.
    """

    code: str
    title: str
    ord: int
    counts_for_verdict: bool
    required_in_nonwork_evening: bool


# The catalogue itself, and **the only place in the codebase that lists kinds of
# anchor**. `app.day` reads the composition off the rule row, `app.crud.anchor`
# reads it off this table; neither names a kind.
#
# Пять первых — края дня из `config.md`. Шестой, `relationship`, — «вечер с
# близкими»: приоритет «здоровье > работа > отношения» до `#92` был выражен на
# две трети, у отношений не было ни якоря, ни колонки. Он единственный, у кого
# `required_in_nonwork_evening` — правило `relationship_anchor_required` живёт в
# `#142`/`#147`, здесь заводится сам вид и его признак.
ANCHOR_KIND_SEED: tuple[AnchorKindSeed, ...] = (
    AnchorKindSeed("подъём", "подъём", 1, True, False),
    AnchorKindSeed("спорт", "спорт", 2, True, False),
    AnchorKindSeed("старт работы", "старт работы", 3, True, False),
    AnchorKindSeed("ревью", "ревью", 4, True, False),
    AnchorKindSeed("отбой", "отбой", 5, True, False),
    AnchorKindSeed(ANCHOR_RELATIONSHIP, "вечер с близкими", 6, True, True),
)

# The composition of anchors the current canon is lived under, and the one the
# imported history was: the evening with the family became part of the canon
# with `#142`, and a day of July is not judged by a rule written in September.
DEFAULT_ANCHOR_CODES: tuple[str, ...] = tuple(seed.code for seed in ANCHOR_KIND_SEED)
LEGACY_ANCHOR_CODES: tuple[str, ...] = tuple(
    seed.code for seed in ANCHOR_KIND_SEED if seed.code != ANCHOR_RELATIONSHIP
)


class AnchorKind(Base):
    """
    A kind of anchor — a row of a catalogue, not a value of an enum.

    The precedent is `health_metrics`: a vocabulary that a person is expected to
    extend has to be extendable by an `INSERT`, because the alternative is that
    «добавить вечер с близкими в канон» means an edit of Python, a migration and
    a deploy. `day_rule_set.anchors` says which of these kinds a given day is
    judged by; this table says what a kind *is*.

    `counts_for_verdict` is here rather than derived from the rule row because
    the two answer different questions: the rule says which anchors this canon
    requires, the catalogue says whether a kind is the sort of thing that can
    lower a day at all.
    """

    __tablename__ = "anchor_kind"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    ord: Mapped[int] = mapped_column(SmallInteger)
    counts_for_verdict: Mapped[bool] = mapped_column(Boolean, server_default="true")
    # Whether the canon expects this anchor in an evening that is not work.
    # The rule that acts on it is `#142`/`#147`; the flag is the vocabulary that
    # rule speaks, and lives with the kind rather than with the rule.
    required_in_nonwork_evening: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )

    def __repr__(self) -> str:
        return f"<AnchorKind(code='{self.code}', ord={self.ord})>"


class DayAnchor(Base):
    """
    One anchor of one day: whether it was closed, and on which line of the plan.

    Until `#92` an anchor was not a thing at all — it was a bullet whose text
    happened to contain «якор», recognised by a substring, and the verdict of a
    day was decided by that recognition. Two consequences followed: a plan that
    worded an anchor differently silently lost it, and no anchor could exist on
    a day whose plan was never written.

    `UNIQUE(day_date, kind)` is the whole point of the row being a row. «Два
    подъёма 30-го» is not a state a person can be in, and a service check would
    be skipped by every writer that does not go through it — an import, a
    migration, a `psql` session.

    `state` is nullable: the anchor of a day that has not happened yet exists
    and says nothing, which is a different fact from «не сделал». `item_id`
    links it to the line of the plan it is written on when there is one, and is
    NULL when the anchor is ticked without a plan — the catalogue does not need
    a plan to exist.
    """

    __tablename__ = "day_anchor"
    __table_args__ = (
        UniqueConstraint("day_date", "kind", name="uq_day_anchor_day_kind"),
        CheckConstraint(
            "state IS NULL OR state IN ('done', 'failed', 'skipped')",
            name="ck_day_anchor_state",
        ),
        Index("ix_day_anchor_kind", "kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    day_date: Mapped[date_type] = mapped_column(
        Date, ForeignKey("day.date", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(
        String(64), ForeignKey("anchor_kind.code", ondelete="RESTRICT")
    )
    # `SET NULL`: rewriting the plan of a day must not take the tick off its
    # anchors — that is the same reasoning `plan_mark` is carried across a
    # replace under.
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("plan_item.id", ondelete="SET NULL"),
        nullable=True,
    )

    state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<DayAnchor(day={self.day_date}, kind='{self.kind}', {self.state})>"
