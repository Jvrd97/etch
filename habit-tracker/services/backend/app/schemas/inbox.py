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
    label: str | None
    direction: str
    is_active: bool
    poll_interval_s: int
    # Имя переменной окружения — запасной путь, оставшийся от первого среза.
    credential_ref: str | None
    # Задан ли секрет. Не значение, не длина, не хвост: экран отвечает на
    # вопрос «надо ли вводить», и большего ему знать незачем.
    has_secret: bool
    # Настройки адаптера без секретов: id воркспейса, лейблы. Их человек и
    # вводил, показывать их обратно — правильно.
    settings: dict[str, str]
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


class CredentialsIn(BaseModel):
    """
    Учётные данные источника, введённые человеком.

    Пустая строка отвергается схемой: «пустой токен» и «нет токена» — одно
    состояние, названное двумя способами, и различать их на экране было бы
    ложью. Чтобы стереть секрет, присылают `null`.
    """

    secret: str | None = Field(default=None, min_length=1)
    # Настройки адаптера: `team_id` у ClickUp, лейблы у почты. Строки, потому
    # что id воркспейса ClickUp — это идентификатор, а не число, которым считают.
    settings: dict[str, str] = Field(default_factory=dict)


class SourcePatch(BaseModel):
    """
    Что у источника разрешено менять снаружи.

    Провайдер и аккаунт не меняются: строка справочника — это тождество
    источника, а не его настройка. Переименование «личного» в «рабочий»
    оставило бы его сигналы и курсор на месте, и вышла бы подмена.
    """

    is_active: bool | None = None
    label: str | None = None
    poll_interval_s: int | None = Field(default=None, ge=60, le=86_400)


class PollResponse(BaseModel):
    """Чем кончился ручной прогон: сколько приехало и сколько обновилось."""

    ingested: int = Field(description="Сигналов, которых раньше не было")
    updated: int = Field(description="Строк, обновивших снимок вместо вставки")


# Сколько строк пробы уезжает на экран. Проба существует ради ответа «видно или
# не видно», и на него хватает первой сотни: воркспейс на две тысячи задач
# отвечает на тот же вопрос ровно так же, а вот в браузер едет мегабайтом.
PROBE_MAX_ITEMS = 100


class ProbeItem(BaseModel):
    """
    Одна внешняя штука так, как её увидела проба.

    Поля те же, что кладёт в базу опрос, и по той же причине: тела контур не
    хранит (ADR-0016, D2), и диагностика — не повод показать его на экране.
    Заголовок, момент и ссылка обратно отвечают на вопрос «это мои задачи?»
    полностью.
    """

    external_id: str
    title: str | None
    external_url: str | None
    occurred_at: datetime


class ProbeResponse(BaseModel):
    """
    Что источник видит снаружи — и ничего из этого не записано.

    `count` считает всё, что вернул адаптер, а `items` обрезаны потолком: иначе
    «показано 100» на воркспейсе из двух тысяч задач читалось бы как «их сто».
    Число и список отвечают на разные вопросы, и путать их здесь дороже всего —
    экран для того и заведён, чтобы ему верили.
    """

    count: int = Field(description="Сколько всего вернул источник")
    items: list[ProbeItem] = Field(
        description=f"Первые {PROBE_MAX_ITEMS} строк — остальные не поехали на экран"
    )
