# [review:need-review] PHASE-03/97
# summary: the inbox contour — the seed of four source stubs, the ClickUp adapter that reads open tasks of the personal workspace by the cursor it keeps, an upsert on the natural key so a second poll of an unchanged workspace adds nothing, and the local date taken from `app.core.daytime` rather than computed here
"""
Чтение внешних источников и запись сигналов.

**Один адаптер на источник, один естественный ключ на всех.** Дедупликация
живёт здесь, а не в адаптере: `(source_id, external_id)` плюс `ON CONFLICT DO
UPDATE` — тем же приёмом, что health-контур. Адаптер отвечает только на вопрос
«что нового у провайдера», и его ответ — список `ExternalItem`, одинаковый для
ClickUp, Gmail и Telegram.

**Локальную дату контур не считает.** Она приходит из
`app.core.daytime.local_date()` — единственного ответа на вопрос «какое сегодня
число» во всём проекте. Своей арифметики поясов здесь нет намеренно: в
personal-os коммит в 00:01 приписался новому дню, и стоило это дня статистики.

**Токен не хранится.** `credential_ref` — имя переменной окружения; значение
читается из окружения процесса в момент запроса и никуда не записывается.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from sqlalchemy import func, literal_column, select
from sqlalchemy.sql.dml import ReturningInsert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.daytime import local_date
from app.models.inbox import (
    TITLE_MAX_CHARS,
    InboundSignal,
    SignalSource,
)

__all__ = [
    "ExternalItem",
    "SignalSource",
    "PollOutcome",
    "PollRefused",
    "SEED_SOURCES",
    "get_source_by_name",
    "list_signals",
    "list_sources",
    "poll_source",
    "seed_sources",
]

# Дословный близнец `SEED_SOURCES` ревизии `c5e7a9b1d3f6`: сид живёт дважды —
# в ревизии для рабочей базы и здесь для тестовой, которую поднимает
# `create_all`. Расхождение ловит тест, сравнивающий оба кортежа.
SEED_SOURCES: tuple[tuple[str, str, str, str | None], ...] = (
    ("clickup", "personal", "read_write", "CLICKUP_PERSONAL_TOKEN"),
    ("clickup", "alvion", "read", "CLICKUP_ALVION_TOKEN"),
    ("gmail", "personal", "read", "GMAIL_PERSONAL_CREDENTIALS"),
    ("telegram", "personal", "read", "TELEGRAM_SESSION_PATH"),
)

CLICKUP_API = "https://api.clickup.com/api/v2"

# Сколько ждём ClickUp. Прогон запускает человек нажатием и ждёт ответа, поэтому
# минуты здесь нет: лучше отказ через двадцать секунд, чем висящая кнопка.
POLL_TIMEOUT_SECONDS = 20.0

# Ключ курсора личного ClickUp: миллисекунды `date_updated` последней виденной
# задачи. Форма курсора — дело адаптера, снаружи это непрозрачный jsonb (D6).
CURSOR_UPDATED_MS = "date_updated_gt"


@dataclass(frozen=True)
class ExternalItem:
    """
    Одна внешняя штука в терминах контура, а не провайдера.

    Тела здесь нет и в переводе из ответа провайдера не появляется: адаптер
    берёт из ответа ровно те поля, которым есть куда лечь.
    """

    external_id: str
    title: str | None
    external_url: str | None
    occurred_at: datetime
    content_hash: str


@dataclass(frozen=True)
class PollOutcome:
    """Чем кончился прогон: сколько приехало нового и сколько обновилось."""

    ingested: int
    updated: int


class PollRefused(Exception):
    """
    Прогон не состоялся, и это не поломка.

    Машинный код, а не текст: он ложится в `signal_sources.last_error_code` и
    показывается экраном как состояние источника. Текст ответа провайдера сюда
    не попадает — диагностика не имеет права стать местом утечки содержимого.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


async def seed_sources(db: AsyncSession) -> None:
    """
    Завести четыре заготовки источников, если их ещё нет.

    Идемпотентно и по естественному ключу: повторный вызов на живой базе ничего
    не трогает, поэтому тестовая база получает тот же справочник, что рабочая
    после ревизии.
    """
    for provider, account, direction, credential_ref in SEED_SOURCES:
        existing = await get_source_by_name(db, provider, account)
        if existing is not None:
            continue
        db.add(
            SignalSource(
                provider=provider,
                account=account,
                direction=direction,
                credential_ref=credential_ref,
                is_active=False,
                cursor={},
            )
        )
    await db.commit()


async def get_source_by_name(
    db: AsyncSession, provider: str, account: str
) -> SignalSource | None:
    result = await db.execute(
        select(SignalSource).where(
            SignalSource.provider == provider, SignalSource.account == account
        )
    )
    return result.scalar_one_or_none()


async def list_sources(db: AsyncSession) -> list[SignalSource]:
    result = await db.execute(
        select(SignalSource).order_by(SignalSource.provider, SignalSource.account)
    )
    return list(result.scalars().all())


async def list_signals(
    db: AsyncSession,
    *,
    state: str | None = None,
    source_id: int | None = None,
    date_from: object | None = None,
    date_to: object | None = None,
    limit: int = 200,
) -> list[InboundSignal]:
    """Лента входящих, свежие сверху."""
    query = select(InboundSignal)
    if state is not None:
        query = query.where(InboundSignal.state == state)
    if source_id is not None:
        query = query.where(InboundSignal.source_id == source_id)
    if date_from is not None:
        query = query.where(InboundSignal.local_date >= date_from)
    if date_to is not None:
        query = query.where(InboundSignal.local_date <= date_to)
    query = query.order_by(InboundSignal.occurred_at.desc(), InboundSignal.id.desc())
    result = await db.execute(query.limit(limit))
    return list(result.scalars().all())


def _hash(*parts: str | None) -> str:
    """
    Отпечаток содержимого, не хранящий содержимого.

    Отвечает ровно на один вопрос — «изменилось ли это с прошлого раза», — и
    именно поэтому в базе лежит он, а не то, из чего он посчитан.
    """
    digest = hashlib.sha256()
    for part in parts:
        digest.update((part or "").encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


async def _read_clickup(
    source: SignalSource, transport: httpx.AsyncBaseTransport | None
) -> list[ExternalItem]:
    """
    Открытые задачи личного воркспейса, изменённые после курсора.

    Токен читается из окружения по имени в `credential_ref`. Его отсутствие —
    отказ с машинным кодом, а не пустой список: «источник не настроен» и «у
    источника ничего нового» — разные ответы, и путать их нельзя.
    """
    name = source.credential_ref
    token = os.environ.get(name or "", "")
    if not token:
        raise PollRefused(
            "no_credentials",
            f"Токена нет: переменная окружения {name or '<не названа>'} пуста. "
            "В базе токен не хранится — только имя переменной.",
        )

    params: dict[str, str] = {"subtasks": "true", "include_closed": "false"}
    since = source.cursor.get(CURSOR_UPDATED_MS)
    if since is not None:
        params["date_updated_gt"] = str(since)

    async with httpx.AsyncClient(
        transport=transport, timeout=POLL_TIMEOUT_SECONDS
    ) as client:
        try:
            response = await client.get(
                f"{CLICKUP_API}/team/{source.account}/task",
                params=params,
                headers={"Authorization": token},
            )
        except httpx.HTTPError as error:
            raise PollRefused("transport_failed", "Источник недоступен.") from error

    if response.status_code >= 400:
        # Код состояния, а не тело ответа: тело может содержать имена задач
        # чужого воркспейса, и в журнале ошибок им не место.
        raise PollRefused(f"http_{response.status_code}", "Источник ответил отказом.")

    items: list[ExternalItem] = []
    for task in response.json().get("tasks", []):
        updated_ms = int(task.get("date_updated") or 0)
        title = (task.get("name") or "")[:TITLE_MAX_CHARS] or None
        items.append(
            ExternalItem(
                external_id=str(task["id"]),
                title=title,
                external_url=task.get("url"),
                occurred_at=datetime.fromtimestamp(updated_ms / 1000, tz=timezone.utc),
                content_hash=_hash(
                    title,
                    (task.get("status") or {}).get("status"),
                    task.get("url"),
                ),
            )
        )
    return items


# Адаптер есть только у личного ClickUp. Остальные три источника стоят в
# справочнике заготовками: экран показывает на них «не подключён», а обратная
# запись отвечает отказом — и оба случая проверяются на настоящей строке.
ADAPTERS = {("clickup", "personal"): _read_clickup}


async def poll_source(
    db: AsyncSession,
    source: SignalSource,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> PollOutcome:
    """
    Спросить источник о новом и записать результат.

    Порядок отказов — от самого дешёвого к самому дорогому: выключенный источник
    и источник без адаптера не доходят до сети вовсе. Это не оптимизация, а
    свойство: «выключен» обязано означать, что наружу не ушло ни одного запроса.
    """
    if not source.is_active:
        raise PollRefused(
            "source_disabled",
            "Источник выключен. Включите его прежде, чем читать.",
        )

    adapter = ADAPTERS.get((source.provider, source.account))
    if adapter is None:
        raise PollRefused(
            "no_adapter",
            f"У источника {source.provider}/{source.account} нет адаптера: "
            "строка в справочнике есть, читать её нечем.",
        )

    try:
        items = await adapter(source, transport)
    except PollRefused as refusal:
        source.last_error_code = refusal.code
        await db.commit()
        raise

    ingested = 0
    updated = 0
    newest_ms = source.cursor.get(CURSOR_UPDATED_MS)
    for item in items:
        # `ON CONFLICT DO UPDATE` по естественному ключу: повторно увиденная
        # задача обновляет снимок. `xmax = 0` в Postgres отличает вставку от
        # обновления — иначе «сколько приехало нового» пришлось бы считать
        # вторым запросом.
        # Аннотация нужна mypy: `returning()` возвращает generic, который
        # из литерала колонки вывести нельзя.
        statement: ReturningInsert[tuple[int, bool]] = (
            pg_insert(InboundSignal)
            .values(
                source_id=source.id,
                external_id=item.external_id,
                title=item.title,
                external_url=item.external_url,
                occurred_at=item.occurred_at,
                local_date=local_date(item.occurred_at),
                content_hash=item.content_hash,
            )
            .on_conflict_do_update(
                constraint="uq_inbound_signal_natural_key",
                set_={
                    "title": item.title,
                    "external_url": item.external_url,
                    "occurred_at": item.occurred_at,
                    "local_date": local_date(item.occurred_at),
                    "content_hash": item.content_hash,
                    "updated_at": func.now(),
                },
            )
            # `xmax = 0` — постгресовый способ отличить вставку от обновления в
            # одном `INSERT ... ON CONFLICT`: у вставленной версии строки нет
            # удаляющей транзакции. Сравнение `created_at = updated_at` тут не
            # работает — `onupdate` до upsert-а не доходит, и обновление
            # считалось бы вставкой.
            .returning(InboundSignal.id, literal_column("xmax = 0"))
        )
        row = (await db.execute(statement)).one()
        if row[1]:
            ingested += 1
        else:
            updated += 1

        stamp = int(item.occurred_at.timestamp() * 1000)
        if newest_ms is None or stamp > int(newest_ms):
            newest_ms = stamp

    # Курсор двигается только после успешной записи: сдвинутый раньше означал бы
    # пропущенные задачи, если запись упала.
    source.cursor = {**source.cursor, CURSOR_UPDATED_MS: newest_ms}
    source.last_polled_at = datetime.now(timezone.utc)
    source.last_error_code = None
    await db.commit()
    return PollOutcome(ingested=ingested, updated=updated)
