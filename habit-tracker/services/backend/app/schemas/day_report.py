# [review:need-review] PHASE-03/145
# summary: проводные типы отчёта дня — одна ревизия с текстом, его хэшем, отчётом каждого источника о себе и списком всех ревизий этой даты, чтобы экран мог переключаться между ними, ничего не досчитывая
"""
Проводные типы отчёта дня.

**Отчёт источника едет наружу целиком.** «Доступен, отдал N записей, пусто
потому-то» — это то, ради чего строка вообще заведена: отчёт беднее прежнего
`.report.md` ровно на коммиты, и человек должен видеть это полем, а не сверять
два текста глазами.

**Список ревизий приезжает вместе с ревизией.** Переключатель на экране иначе
пришлось бы собирать вторым запросом или угадывать по номеру, а «сколько раз
пересобирали» — часть ответа на вопрос «на чём построен завтрашний день».
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.day_report import REPORT_TRIGGERS


class DayReportSource(BaseModel):
    """Что один источник отдал отчёту и почему не больше."""

    available: bool = Field(
        ..., description="Был ли источник доступен: контур подключён и данные есть"
    )
    count: int = Field(0, description="Сколько записей источник отдал")
    note: str = Field(
        "",
        description=(
            "Почему записей нет. Пусто — источник отдал их и объяснять нечего"
        ),
    )


class DayReportResponse(BaseModel):
    """Одна ревизия отчёта дня, как её читает экран."""

    day_date: date
    revision: int = Field(..., description="Номер ревизии; 0 — первая сборка")
    trigger: str = Field(
        ..., description=f"Повод сборки: {' | '.join(REPORT_TRIGGERS)}"
    )
    content_md: str
    content_hash: str = Field(
        ..., description="sha256 от `content_md`: тот же хэш — те же данные"
    )
    sources: dict[str, DayReportSource] = Field(
        default_factory=dict,
        description="Отчёт каждого источника о себе, ключом источника",
    )
    built_at: datetime
    revisions: list[int] = Field(
        default_factory=list,
        description="Все ревизии этой даты по возрастанию — для переключателя",
    )
