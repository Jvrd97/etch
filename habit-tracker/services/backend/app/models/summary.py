# [review:need-review] PHASE-03/90, PHASE-03/143, PHASE-03/144
# summary: `day_summary` — the verdict of a day with the rule it was reached under, the counters behind it, the prose made searchable by a generated tsvector, the CHECK that makes an override without a note impossible for every writer, the stage of closing with the two idempotency keys that make each of the two touches repeatable, and the reading of where the verdict came from — computed here or carried over from prose and never to be recomputed
from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base
from app.day.evaluate import VERDICTS
from app.models.checks import in_list

# The generated column, spelled once so the model and the migration cannot
# drift. A two-argument `to_tsvector` is immutable, which is what lets postgres
# store it rather than recompute it on every read.
SEARCH_EXPR = "to_tsvector('russian', body_md)"

# Where the row came from. `close` is a day a person (or the agent on their
# behalf) closed here; `import` is a verdict that arrived as prose from
# `personal-os` and was never computed. The distinction is what makes
# «импортированные вердикты не пересчитываются» expressible at all: without it
# a recompute has no way to tell a judgement it may redo from one it may not.
SOURCE_CLOSE = "close"
SOURCE_IMPORT = "import"
SUMMARY_SOURCES: tuple[str, ...] = (SOURCE_CLOSE, SOURCE_IMPORT)

# How far the closing of the day got. Закрытие идёт в два касания — около 15:40
# факт по рабочим задачам, вечером якоря и вердикт, — и до `#143` в базе это
# было одно событие, так что день, где ревью в 15:40 не случилось, ничем не
# отличался от дня, где оно было.
#
# `open` is the stage of a day that has no row here at all: the live block
# `GET /day/{date}` answers with carries it, and the column accepts it so that
# the vocabulary is one list rather than two. Stored rows are `reviewed` or
# `closed`.
STAGE_OPEN = "open"
STAGE_REVIEWED = "reviewed"
STAGE_CLOSED = "closed"
SUMMARY_STAGES: tuple[str, ...] = (STAGE_OPEN, STAGE_REVIEWED, STAGE_CLOSED)

# Откуда взялся вердикт, который читает экран. ADR-0015 называет это поле
# `verdict_reason.source = "migrated_prose"`; в базе тот же факт уже записан
# колонкой `source`, и второе его написание было бы вторым мнением о том, можно
# ли этот день пересчитывать. Поэтому происхождение — производная, а не колонка:
# оно вычисляется здесь одним написанием и едет наружу в DTO.
ORIGIN_COMPUTED = "computed"
ORIGIN_MIGRATED_PROSE = "migrated_prose"
ORIGIN_NONE = "none"
VERDICT_ORIGINS: tuple[str, ...] = (
    ORIGIN_COMPUTED,
    ORIGIN_MIGRATED_PROSE,
    ORIGIN_NONE,
)


def verdict_origin(source: str, verdict: str | None) -> str:
    """
    Вычислен вердикт или перенесён из прозы — и есть ли он вообще.

    Пустой вердикт даёт `none` независимо от источника: у дня, который никто не
    судил, происхождения суждения нет, и `computed` на нём читалось бы как
    «машина посчитала и получила ничего». Строка `source='import'` с вердиктом —
    `migrated_prose`: её нельзя пересчитывать, и экран обязан подписать её «из
    записи», а не выдавать за вычисленную.
    """
    if verdict is None:
        return ORIGIN_NONE
    return ORIGIN_MIGRATED_PROSE if source == SOURCE_IMPORT else ORIGIN_COMPUTED


class DaySummary(Base):
    """
    The итог of one day: what the verdict was, and everything it stands on.

    **Строка одна на дату, и на ней написано, как далеко зашло закрытие.** Since
    `#143` «день закрыт» is `stage = 'closed'` rather than the mere existence of
    the row: касание 15:40 пишет `reviewed`, вечернее — `closed`. A boolean
    beside the stage would be a second answer to the same question, so there is
    none. `GET /day/{date}` answers with a live recount and `verdict = null`
    while the day is not closed, which is how «не закрыл» stays a different fact
    from «проиграл» — and `stage = 'reviewed'` splits that further into «рано»
    rather than «проиграл».

    **`rule_set_id` is stored, not derived.** The canon changed on 2026-08-17
    and will change again; a verdict that does not carry the numbers it was
    measured against cannot be re-read a month later, and re-deriving it on
    display would silently re-judge the past.

    **Проза никуда не девается.** «Что случилось вместо плана», «Что мешало» и
    оговорка «цифра 0/4 измеряет не работу, а её видимость» — половина ценности
    записи, and `body_md` with a generated `tsvector` and a GIN index is what
    keeps it findable instead of merely stored.

    **Переопределение вердикта требует записки, и это правило базы.** The
    Pydantic validator is a message; this CHECK is the rule. Человек имеет право
    сказать «день был выигран, просто я не отметил» — но вслух, а не молчаливой
    правкой, and that has to hold for a `psql` session as much as for the API.
    """

    __tablename__ = "day_summary"
    __table_args__ = (
        CheckConstraint(in_list("verdict", VERDICTS), name="ck_day_summary_verdict"),
        CheckConstraint(
            in_list("source", SUMMARY_SOURCES), name="ck_day_summary_source"
        ),
        CheckConstraint(
            "NOT verdict_override OR verdict_override_note IS NOT NULL",
            name="ck_day_summary_override_has_note",
        ),
        CheckConstraint(in_list("stage", SUMMARY_STAGES), name="ck_day_summary_stage"),
        # «До `final` вердикта нет»: `verdict = NULL` на стадии `reviewed`
        # значит «рано», а не «проиграл». A rule of the base rather than of the
        # service, because a verdict written onto a half-closed day would be
        # indistinguishable afterwards from one the evening produced.
        CheckConstraint(
            f"stage = '{STAGE_CLOSED}' OR verdict IS NULL",
            name="ck_day_summary_verdict_needs_closed",
        ),
        UniqueConstraint(
            "review_idempotency_key", name="uq_day_summary_review_idempotency_key"
        ),
        UniqueConstraint(
            "final_idempotency_key", name="uq_day_summary_final_idempotency_key"
        ),
        Index("ix_day_summary_search", "search", postgresql_using="gin"),
    )

    # The day is the key: one итог per date, replaced in place. The attribute is
    # not called `date` for the reason `Day.day_date` is not — see that model.
    day_date: Mapped[date_type] = mapped_column(
        "day_date", Date, ForeignKey("day.date", ondelete="CASCADE"), primary_key=True
    )
    rule_set_id: Mapped[int] = mapped_column(ForeignKey("day_rule_set.id"))

    # Как далеко зашло закрытие. Стадия живёт здесь, а не в отдельной таблице
    # `day_closing` из ADR-0015: итог дня уже целиком в этой строке, и двух
    # хранилищ одного итога в одной базе быть не должно.
    #
    # `closed` по умолчанию — так строка, написанная импортом или существовавшая
    # до `#143`, читается как закрытый день, каким она и является.
    stage: Mapped[str] = mapped_column(Text, server_default=STAGE_CLOSED)
    # NULL — касания 15:40 не было. Это обычный день, а не ошибка: стадия тогда
    # прыгает `open → closed`, и `review_skipped` в ответе считается ровно по
    # этой паре (`stage='closed'` при пустом `reviewed_at`), без второй колонки,
    # которая рано или поздно разошлась бы с первой.
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Ключи идемпотентности двух касаний, по образцу `applied_daily_summaries`.
    # Уникальны каждый сам по себе: один ключ закрывает одно касание одного дня,
    # и повтор с тем же ключом обязан вернуть ту же строку, ничего не записав.
    # NULL здесь — «касание пришло без ключа», и таких строк может быть сколько
    # угодно: в postgres NULL уникальности не нарушает.
    review_idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)

    # NULL while nothing judged the day — an imported summary whose prose says
    # «вне игры (выходной)» is exactly that, and so is a row on stage
    # `reviewed`: закрытие началось и не дошло до вечера.
    verdict: Mapped[str | None] = mapped_column(Text, nullable=True)
    verdict_reason: Mapped[str] = mapped_column(Text, server_default="")

    verdict_override: Mapped[bool] = mapped_column(Boolean, server_default="false")
    verdict_override_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    anchors_done: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    anchors_total: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    tasks_done: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    tasks_total: Mapped[int] = mapped_column(SmallInteger, server_default="0")

    # NULL means "не измерено", never zero. Intervals of work are `#91`; until
    # then the number arrives in the body of `POST /close` or not at all.
    work_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Derived from the verdicts of every earlier day, recomputed as a whole —
    # stored because the screen reads it per day and a running fold on every
    # render would be the second place a streak is computed.
    streak_after: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # The three questions `/day-close` asks and nothing else records: писал ли
    # сам, сколько вопросов Education висит, сделано ли ревью.
    wrote_from_scratch: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    education_debt: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    reviewed_today: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    body_md: Mapped[str] = mapped_column(Text, server_default="")
    # What the day could not be judged on, as machine codes. The Russian a
    # person reads lives in `lib/day-format.ts`, the way `verdict_reason` does.
    missing_data: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default="{}"
    )
    source: Mapped[str] = mapped_column(Text, server_default=SOURCE_CLOSE)

    search: Mapped[Any] = mapped_column(
        TSVECTOR, Computed(SEARCH_EXPR, persisted=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<DaySummary(day_date={self.day_date}, verdict={self.verdict!r})>"
