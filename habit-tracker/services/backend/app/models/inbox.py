# [review:need-review] PHASE-03/97
# summary: the five tables of ADR-0016 — `signal_sources` with its opaque jsonb cursor, the allowlist `signal_scopes`, the source-agnostic envelope `inbound_signals` whose privacy is expressed by the columns it does not have, the derived `commitments`, and the journal `signal_mirror_ops` of what was written back
"""
Входящие сигналы: ClickUp, Telegram, Gmail — одним слоем.

**Приватность выражена отсутствием колонок (ADR-0016, D2).** Тела писем, текстов
сообщений и вложений здесь нет физически, и это не забывчивость: дамп Postgres
лежит файлом на диске VPS (`deploy/backup.sh`), и колонка под тело сделала бы из
бэкапа копию всей личной переписки. Хранится указатель — `external_url` вернёт
человека к оригиналу одним кликом, — а не копия. `title` есть только там, где
заголовок и есть титул: имя задачи ClickUp, тема письма; у Telegram он всегда
`NULL`. Собеседник опознаётся `counterpart_key` = sha256(peer + соль): «тот же
человек, что и в прошлый раз» без ответа на вопрос, кто это.

**Дедупликация — естественный ключ (D5).** `UNIQUE (source_id, external_id)` плюс
`ON CONFLICT DO UPDATE`, тем же приёмом, что `uq_health_hour_bucket_natural_key`:
повторно увиденная задача обновляет снимок, а не плодит строку. `content_hash`
отвечает, изменилось ли содержимое, не храня содержимого.

**Курсор — jsonb на источнике (D6).** У ClickUp это миллисекунды `date_updated_gt`,
у Gmail — `historyId` и запасной `after:<epoch>`, у Telegram — `pts` по диалогам.
Ничто не ищет по курсору: ровно тот случай, для которого jsonb и существует.

**Словари — плоские строки без PG-enum**, по образцу `chat_messages.status`:
шестое состояние стоит правки кода, а не миграции.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base

# Куда ходит адаптер. Имя источника — `<provider>/<account>`: один провайдер
# может стоять дважды, личный ClickUp и рабочий Alvion — разные источники с
# разными правами.
SOURCE_PROVIDER_CLICKUP = "clickup"
SOURCE_PROVIDER_GMAIL = "gmail"
SOURCE_PROVIDER_TELEGRAM = "telegram"
SOURCE_PROVIDERS: tuple[str, ...] = (
    SOURCE_PROVIDER_CLICKUP,
    SOURCE_PROVIDER_GMAIL,
    SOURCE_PROVIDER_TELEGRAM,
)

# Что источнику позволено. `read_write` — единственный, из которого уходит
# обратная запись, и это только личный ClickUp (D7): в Alvion статус задачи
# что-то значит для команды.
SOURCE_DIRECTION_READ = "read"
SOURCE_DIRECTION_READ_WRITE = "read_write"
SOURCE_DIRECTIONS: tuple[str, ...] = (
    SOURCE_DIRECTION_READ,
    SOURCE_DIRECTION_READ_WRITE,
)

# Состояние разбора сигнала. `new` — приехал и не разобран; `parsed` — из него
# родилось обязательство; `ignored` — человек сказал «не надо»; `duplicate` —
# то же обязательство уже приехало другим источником (D5: кросс-источниковую
# дедупликацию делает человек одним нажатием, а не модель).
SIGNAL_STATE_NEW = "new"
SIGNAL_STATE_PARSED = "parsed"
SIGNAL_STATE_IGNORED = "ignored"
SIGNAL_STATE_DUPLICATE = "duplicate"
SIGNAL_STATES: tuple[str, ...] = (
    SIGNAL_STATE_NEW,
    SIGNAL_STATE_PARSED,
    SIGNAL_STATE_IGNORED,
    SIGNAL_STATE_DUPLICATE,
)

COMMITMENT_STATUS_PROPOSED = "proposed"
COMMITMENT_STATUS_ACCEPTED = "accepted"
COMMITMENT_STATUS_DONE = "done"
COMMITMENT_STATUS_DROPPED = "dropped"
COMMITMENT_STATUSES: tuple[str, ...] = (
    COMMITMENT_STATUS_PROPOSED,
    COMMITMENT_STATUS_ACCEPTED,
    COMMITMENT_STATUS_DONE,
    COMMITMENT_STATUS_DROPPED,
)

# Что писалось наружу и чем кончилось. Журнал ведётся и на успех, и на отказ:
# «повтор того же запроса не шлёт второй PUT» (D7) проверяется по этой таблице.
MIRROR_OP_COMPLETE = "complete"
MIRROR_OPS: tuple[str, ...] = (MIRROR_OP_COMPLETE,)

MIRROR_STATUS_PENDING = "pending"
MIRROR_STATUS_DONE = "done"
MIRROR_STATUS_FAILED = "failed"
MIRROR_STATUSES: tuple[str, ...] = (
    MIRROR_STATUS_PENDING,
    MIRROR_STATUS_DONE,
    MIRROR_STATUS_FAILED,
)

# Длина заголовка, который мы соглашаемся хранить. Режется адаптером, а не
# базой: обрезанный заголовок лучше, чем прогон, упавший на длинном имени.
TITLE_MAX_CHARS = 300


class SignalSource(Base):
    """
    Один внешний аккаунт, у которого мы спрашиваем новое.

    Токен здесь не лежит и лежать не может: `credential_ref` — это **имя
    переменной окружения**, а не её значение. Секрет живёт в окружении процесса,
    и дамп базы его не выносит.

    `cursor` непрозрачен для всех, кроме своего адаптера, — см. D6.
    """

    __tablename__ = "signal_sources"
    __table_args__ = (
        UniqueConstraint("provider", "account", name="uq_signal_source_account"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    provider: Mapped[str] = mapped_column(String(20))
    # Какой именно аккаунт провайдера: `personal`, `alvion`.
    account: Mapped[str] = mapped_column(String(50))
    direction: Mapped[str] = mapped_column(
        String(16), server_default=SOURCE_DIRECTION_READ
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="false")

    # Имя env-переменной с токеном — путь, оставшийся от первого среза.
    # Читается, когда своего секрета у источника нет: так живой прод с токеном в
    # окружении продолжает работать после того, как хранилище появилось.
    credential_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Секрет источника, зашифрованный ключом из `SESSION_SECRET`
    # (`app/inbox/credentials.py`). Открытого текста в базе нет; в дампе лежит
    # шифротекст, ключ живёт в окружении процесса.
    secret_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Настройки адаптера: у ClickUp — числовой id воркспейса, у Gmail будут
    # лейблы. Непрозрачный jsonb по той же причине, что и курсор: типизированные
    # колонки под каждого провайдера стояли бы пустыми у остальных.
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, server_default="{}")
    # Подпись, которую вписывает человек: «Личный», «Alvion». Адаптер её не
    # тянет из источника — имена чужих воркспейсов система не хранит.
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Как часто воркер `#99` спрашивает источник. В строке, а не в константе:
    # у почты и у задач разный смысл «свежести».
    poll_interval_s: Mapped[int] = mapped_column(Integer, server_default="900")
    cursor: Mapped[dict[str, Any]] = mapped_column(JSON, server_default="{}")

    last_polled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Машинный код последнего отказа, без текста ответа: диагностика не имеет
    # права стать местом, куда протекает содержимое чужого ящика.
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<SignalSource({self.provider}/{self.account})>"


class SignalScope(Base):
    """
    Allowlist: что именно у источника разрешено читать (D3).

    Пустой allowlist означает «ничего»: «читаем личные чаты» — это выбранный
    руками набор, а не «все диалоги». Для ClickUp ключ — id списка, для Gmail —
    лейбл, для Telegram — id чата.
    """

    __tablename__ = "signal_scopes"
    __table_args__ = (
        UniqueConstraint("source_id", "scope_key", name="uq_signal_scope_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("signal_sources.id", ondelete="CASCADE"), index=True
    )

    scope_key: Mapped[str] = mapped_column(String(100))
    # Человеческое имя скоупа — чтобы экран не показывал голый id списка.
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<SignalScope(source_id={self.source_id}, key={self.scope_key!r})>"


class InboundSignal(Base):
    """
    Один сигнал: что-то произошло снаружи и может требовать ответа.

    Колонок под тело, отправителя и вложения здесь нет физически — это и есть
    приватность контура (D2). Всё, что известно: откуда, какой внешний id, когда
    произошло, каким днём это считается, ссылка обратно и состояние разбора.
    """

    __tablename__ = "inbound_signals"
    __table_args__ = (
        UniqueConstraint(
            "source_id", "external_id", name="uq_inbound_signal_natural_key"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("signal_sources.id", ondelete="CASCADE"), index=True
    )
    scope_id: Mapped[int | None] = mapped_column(
        ForeignKey("signal_scopes.id", ondelete="SET NULL"), nullable=True, index=True
    )

    external_id: Mapped[str] = mapped_column(String(200))
    # Заголовок — только там, где он и есть титул: имя задачи, тема письма.
    # У Telegram всегда NULL, и это правило контура, а не свойство адаптера.
    title: Mapped[str | None] = mapped_column(String(TITLE_MAX_CHARS), nullable=True)
    external_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Истинный момент из источника и день, которым его считает приложение.
    # Дата приходит из `app.core.daytime.local_date()`, своей арифметики поясов
    # в контуре нет: коммит в 00:01 не имеет права приписаться новому дню.
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    local_date: Mapped[date_type] = mapped_column(Date, index=True)

    state: Mapped[str] = mapped_column(String(16), server_default=SIGNAL_STATE_NEW)
    # Изменилось ли содержимое с прошлого раза — без хранения содержимого.
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # sha256(peer + соль): тот же человек, без ответа на вопрос, кто это.
    counterpart_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"<InboundSignal(id={self.id}, source_id={self.source_id}, "
            f"external_id={self.external_id!r}, state={self.state!r})>"
        )


class Commitment(Base):
    """
    Обязательство, выведенное из сигнала, — то, что человек принял или отклонил.

    Отдельная таблица, а не колонка сигнала: сигнал неизменяем и говорит «что
    случилось», обязательство изменяемо и говорит «что я с этим делаю». Из
    одного письма может родиться два обязательства, а из ста сигналов — ни
    одного.

    `due_local_date` — единственная привязка ко дню (D6). Без срока обязательство
    не привязано ни к какому дню, и в частности не к сегодняшнему.
    """

    __tablename__ = "commitments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    signal_id: Mapped[int | None] = mapped_column(
        ForeignKey("inbound_signals.id", ondelete="SET NULL"), nullable=True, index=True
    )

    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(16), server_default=COMMITMENT_STATUS_PROPOSED
    )
    due_local_date: Mapped[date_type | None] = mapped_column(
        Date, nullable=True, index=True
    )
    # Насколько модель уверена в разборе, 0..100. Целое, а не float: точность
    # ниже процента здесь ничего не значит, а сравнивать целые проще.
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<Commitment(id={self.id}, status={self.status!r})>"


class SignalMirrorOp(Base):
    """
    Попытка записать наружу — одна строка на попытку, успешную и нет.

    Ключ идемпотентности рождается на клиенте и уникален: повтор того же запроса
    обязан быть повтором, а не вторым PUT в ClickUp (D7).
    """

    __tablename__ = "signal_mirror_ops"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_signal_mirror_idempotency"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    signal_id: Mapped[int] = mapped_column(
        ForeignKey("inbound_signals.id", ondelete="CASCADE"), index=True
    )

    op: Mapped[str] = mapped_column(String(20), server_default=MIRROR_OP_COMPLETE)
    status: Mapped[str] = mapped_column(
        String(16), server_default=MIRROR_STATUS_PENDING
    )
    idempotency_key: Mapped[str] = mapped_column(String(100))
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<SignalMirrorOp(signal_id={self.signal_id}, status={self.status!r})>"
