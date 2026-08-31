# [review:need-review] PHASE-03/127, PHASE-03/129
# summary: the two challenge tables — `challenges` (the promise: rule, window, failure mode, status) and `challenge_days` (one verdict per day, unique on `(challenge_id, day)` so a re-materialization lands on the row it already wrote)
"""
Челлендж как обязательство: правило, окно, вердикт на каждый день.

**Отдельная пара таблиц, а не поле-цель у категории.** Цель на категории
означала бы один челлендж на категорию, потерю завершённых при смене цели и
молчаливую переоценку прошлых дней при её правке. А нужна ровно история
обязательств — «сколько раз я это заваливал».

**Измерений здесь не хранится.** Числа остаются в `entry_values`; челлендж
хранит правило — пару `(category_id, field_id)` и вид. Второго источника истины
про «сколько я выпил воды» не появляется.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base
from app.models.checks import in_list

# Как челлендж заканчивается. `any_miss` — первый промах заваливает;
# `budget` — заваливает `allowed_misses + 1`-й.
FAILURE_ANY_MISS = "any_miss"
FAILURE_BUDGET = "budget"
FAILURE_MODES: tuple[str, ...] = (FAILURE_ANY_MISS, FAILURE_BUDGET)

STATUS_ACTIVE = "active"
STATUS_WON = "won"
STATUS_FAILED = "failed"
STATUS_ABANDONED = "abandoned"
# Обязательство, которое ещё никто на себя не взял: предложено, не принято.
# Дни для него не материализуются и счёт не идёт — до тех пор, пока человек не
# нажмёт «принять».
STATUS_PROPOSED = "proposed"
CHALLENGE_STATUSES: tuple[str, ...] = (
    STATUS_PROPOSED,
    STATUS_ACTIVE,
    STATUS_WON,
    STATUS_FAILED,
    STATUS_ABANDONED,
)

# Откуда челлендж взялся. На расчёт не влияет вовсе — влияет на путь появления:
# человек заводит обязательство сразу активным, модель и план дня только
# предлагают.
ORIGIN_HUMAN = "human"
ORIGIN_AI = "ai"
ORIGIN_PLAN = "plan"
CHALLENGE_ORIGINS: tuple[str, ...] = (ORIGIN_HUMAN, ORIGIN_AI, ORIGIN_PLAN)
# Источники, которым запись в базу разрешена только через предложение. Одной
# галлюцинации в JSON достаточно, чтобы завести человеку обязательство без
# спроса, поэтому правило держит сервер, а не промпт.
MACHINE_ORIGINS: tuple[str, ...] = (ORIGIN_AI, ORIGIN_PLAN)

# Статусы, из которых пересчёт назад не отыгрывает: раз закрытая история
# обязательства сама себя не переписывает.
TERMINAL_STATUSES: tuple[str, ...] = (STATUS_WON, STATUS_FAILED, STATUS_ABANDONED)


class Challenge(Base):
    """
    Одно обязательство: «7 дней подряд ≥ 2 л воды».

    Внешние ключи на категорию и поле — `RESTRICT`: удалить категорию, на
    которой висит история обязательств, значит потерять сам факт, что они были.
    Отказ на удалении честнее, чем каскад.
    """

    __tablename__ = "challenges"
    __table_args__ = (
        # Окно, которое кончается раньше, чем начинается, отказывает база, а не
        # схема: `psql`, импорт и будущий писатель тоже должны получить отказ.
        CheckConstraint("ends_on >= starts_on", name="ck_challenge_window"),
        CheckConstraint("allowed_misses >= 0", name="ck_challenge_allowed_misses"),
        # Читательский путь списка: активные челленджи, у которых окно ещё не
        # кончилось.
        Index("ix_challenges_status_ends", "status", "ends_on"),
        # Словари статуса и источника — те же, что в миграции, и написаны из
        # тех же кортежей. Без них `create_all` строит таблицу без CHECK, и
        # тесты пропускают статус, который прод отвергнет (#129).
        CheckConstraint(
            in_list("status", CHALLENGE_STATUSES), name="ck_challenge_status"
        ),
        CheckConstraint(
            in_list("origin", CHALLENGE_ORIGINS), name="ck_challenge_origin"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    title: Mapped[str] = mapped_column(String(200))

    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), index=True
    )
    field_id: Mapped[int] = mapped_column(
        ForeignKey("fields.id", ondelete="RESTRICT"), index=True
    )

    rule_kind: Mapped[str] = mapped_column(String(20))
    # Порог правила; NULL у `checked` и `abstain`, которым сравнивать не с чем.
    target: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)

    starts_on: Mapped[date_type] = mapped_column(Date)
    ends_on: Mapped[date_type] = mapped_column(Date)

    failure_mode: Mapped[str] = mapped_column(
        String(10), server_default=FAILURE_ANY_MISS
    )
    allowed_misses: Mapped[int] = mapped_column(SmallInteger, server_default="0")

    status: Mapped[str] = mapped_column(String(12), server_default=STATUS_ACTIVE)
    # Кто предложил обязательство. Строки, написанные до #129, — человеческие:
    # другого пути завести челлендж тогда не было.
    origin: Mapped[str] = mapped_column(String(6), server_default=ORIGIN_HUMAN)
    # День, на котором бюджет промахов кончился. NULL, пока челлендж жив.
    failed_on: Mapped[date_type | None] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    days: Mapped[list[ChallengeDay]] = relationship(
        back_populates="challenge",
        cascade="all, delete-orphan",
        order_by="ChallengeDay.day",
    )

    def __repr__(self) -> str:
        # Без заголовка: `__repr__` попадает в логи и трейсбеки, а заголовок
        # челленджа — это то, что человек про себя обещал.
        return f"<Challenge(id={self.id}, kind='{self.rule_kind}', status='{self.status}')>"


class ChallengeDay(Base):
    """
    Вердикт одного дня обязательства.

    Естественный ключ — `(challenge_id, day)`, и материализация пишет по нему
    upsert'ом. Отсюда свойство, ради которого он и заведён: два `recompute`
    подряд оставляют то же число строк, а челлендж, о котором забыли на неделю,
    досчитывается разом.

    `source` разводит вердикт, который посчитал сервер, и вердикт, который
    поставил человек. Второй пересчёт **никогда** не перетирает: ручной ввод
    правит автоматику, а не наоборот.
    """

    __tablename__ = "challenge_days"
    __table_args__ = (
        UniqueConstraint("challenge_id", "day", name="uq_challenge_day"),
        Index("ix_challenge_days_day", "day"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    challenge_id: Mapped[int] = mapped_column(
        ForeignKey("challenges.id", ondelete="CASCADE"), index=True
    )

    day: Mapped[date_type] = mapped_column(Date)
    verdict: Mapped[str] = mapped_column(String(10))
    source: Mapped[str] = mapped_column(String(10), server_default="computed")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    challenge: Mapped[Challenge] = relationship(back_populates="days")

    def __repr__(self) -> str:
        return (
            f"<ChallengeDay(challenge_id={self.challenge_id}, day={self.day}, "
            f"verdict='{self.verdict}', source='{self.source}')>"
        )
