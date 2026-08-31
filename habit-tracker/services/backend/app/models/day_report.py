# [review:need-review] PHASE-03/145
# summary: `day_report` — отчёт дня строкой базы вместо файла `plans/**/<дата>.report.md`: неизменяемая ревизия с текстом, его sha256, отчётом каждого источника в jsonb и поводом сборки
"""
Отчёт дня как строка, а не как файл, собранный на лету.

**Почему строка.** Сегодня отчёт собирается из четырёх источников сразу —
отметки со страницы, блокнот дня, `git log` в подпроцессе, файлы `notes/**` — и
потому не воспроизводится дважды одинаково и не тестируется целиком. Строка с
текстом и его хэшем делает и то и другое: тест гоняется на голой базе, а два
одинаковых прогона дают один хэш.

**Ревизия неизменяема.** Пересборка не правит текст, а добавляет строку с
`revision + 1`. План на завтра вырастает из отчёта, и «на чём он был построен» —
вопрос, у которого через месяц должен быть ответ; отчёт, переписанный поверх,
такого ответа не даёт.

**`content_hash` отсекает пустую ревизию.** sha256 от `content_md`: пересборка
на неизменившихся данных узнаёт себя и возвращает ту же строку вместо того,
чтобы копить одинаковые ревизии на каждое нажатие кнопки.

**`sources` объясняет пустоту.** Каждый источник отчитывается сам: доступен ли,
сколько записей отдал и почему их нет. Пока контур сигналов не подключён
(`#146`), отчёт беднее прежнего `.report.md` — в нём нет коммитов, — и это видно
полем, а не догадкой читателя.
"""

from __future__ import annotations

import uuid
from datetime import date as date_type
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base
from app.models.checks import in_list

# Что вызвало сборку. `close` — вечернее касание закрытия, `button` — кнопка
# «сделать план на завтра», `nightly` — ночной прогон-страховка (`#151`), `api` —
# явный `POST` руками или из скилла. Повод хранится, потому что «отчёт собрался
# сам ночью» и «человек нажал кнопку» — разные основания доверять тексту.
TRIGGER_CLOSE = "close"
TRIGGER_BUTTON = "button"
TRIGGER_NIGHTLY = "nightly"
TRIGGER_API = "api"
REPORT_TRIGGERS: tuple[str, ...] = (
    TRIGGER_CLOSE,
    TRIGGER_BUTTON,
    TRIGGER_NIGHTLY,
    TRIGGER_API,
)

TRIGGER_LENGTH = 16
# sha256 в шестнадцатеричном виде — ровно 64 знака.
HASH_LENGTH = 64


class DayReport(Base):
    """Одна ревизия отчёта одного дня."""

    __tablename__ = "day_report"
    __table_args__ = (
        CheckConstraint(
            in_list("trigger", REPORT_TRIGGERS), name="ck_day_report_trigger"
        ),
        # Ревизии нумеруются с нуля и внутри даты: «ревизия 3» без даты — не
        # адрес. Уникальность здесь и есть то, что делает пересборку добавлением,
        # а не правкой.
        UniqueConstraint("day_date", "revision", name="uq_day_report_revision"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    day_date: Mapped[date_type] = mapped_column(
        Date, ForeignKey("day.date", ondelete="CASCADE"), index=True
    )
    revision: Mapped[int] = mapped_column(Integer)
    trigger: Mapped[str] = mapped_column(String(TRIGGER_LENGTH))

    content_md: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(HASH_LENGTH))

    # `{источник: {available, count, note}}`. Столбец, а не таблица: отчёт
    # источника живёт ровно столько, сколько ревизия, и читается только вместе
    # с ней.
    sources: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )

    built_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<DayReport(day_date={self.day_date}, revision={self.revision})>"
