# [review:need-review] PHASE-03/97
# summary: wire types of the inbox — a source with its state and the name (not the value) of the credential it needs, a signal with the link back and no field into which a body could ever fit, and the outcome of one poll as two counts
"""
Наружные типы контура входящих.

Тела нет и в проводе: DTO повторяет форму таблиц, где колонки под содержимое
нет физически (ADR-0016, D2). Наружу уходит указатель — `external_url`, — а не
копия письма или сообщения.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class SourceResponse(BaseModel):
    """Источник в справочнике: что это, читаем ли, когда читали в последний раз."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: str
    account: str
    direction: str
    is_active: bool
    # Имя переменной окружения, а не токен. Наружу уходит именно имя: экран
    # показывает, чего не хватает, не показывая секрета.
    credential_ref: str | None
    last_polled_at: datetime | None
    last_error_code: str | None


class SignalResponse(BaseModel):
    """
    Один входящий сигнал.

    `title` есть там, где заголовок и есть титул: имя задачи, тема письма. У
    Telegram он всегда `null` — правило контура, а не свойство адаптера.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: int
    external_id: str
    title: str | None
    external_url: str | None
    occurred_at: datetime
    local_date: date
    state: str


class PollResponse(BaseModel):
    """Чем кончился ручной прогон: сколько приехало и сколько обновилось."""

    ingested: int = Field(description="Сигналов, которых раньше не было")
    updated: int = Field(description="Строк, обновивших снимок вместо вставки")
