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
from typing import Protocol

import httpx
from sqlalchemy import func, literal_column, select
from sqlalchemy.sql.dml import ReturningInsert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.daytime import local_date
from app.inbox.credentials import SecretUnreadable, decrypt_secret, encrypt_secret
from app.models.inbox import (
    SOURCE_DIRECTION_READ_WRITE,
    TITLE_MAX_CHARS,
    InboundSignal,
    SignalSource,
)

__all__ = [
    "ExternalItem",
    "may_write_back",
    "set_credentials",
    "SignalSource",
    "PollOutcome",
    "PollRefused",
    "probe_source",
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

# Переменная окружения с числовым id личного воркспейса. Отдельно от токена:
# один и тот же токен видит несколько воркспейсов, и какой из них «личный» —
# решение человека, а не свойство ключа.
CLICKUP_TEAM_ENV = "CLICKUP_PERSONAL_TEAM_ID"

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


async def set_credentials(
    db: AsyncSession,
    source: SignalSource,
    *,
    secret: str | None,
    settings: dict[str, str] | None = None,
) -> SignalSource:
    """
    Задать источнику учётные данные, не выходя с сервера.

    `secret=None` стирает секрет — способ отключить источник, не удаляя его
    настроек. Пустая строка сюда не доходит: её отвергает схема запроса, потому
    что «пустой токен» и «нет токена» — одно состояние, названное двумя словами.

    Курсор при смене секрета не сбрасывается намеренно: другой токен к тому же
    воркспейсу видит те же задачи, а перечитывание всего воркспейса заново стоит
    сотни строк, которые человек уже разобрал.
    """
    source.secret_ciphertext = None if secret is None else encrypt_secret(secret)
    if settings is not None:
        source.settings = {**source.settings, **settings}
    # Прошлый отказ перестаёт быть правдой: новые данные ещё не проверены, и
    # держать на экране «нет токена» после ввода токена — врать.
    source.last_error_code = None
    await db.commit()
    await db.refresh(source)
    return source


def may_write_back(source: SignalSource) -> bool:
    """
    Можно ли писать в источник обратно.

    Только `read_write`, а это только личный ClickUp (ADR-0016, D7): в рабочем
    воркспейсе статус задачи что-то значит для команды, и закрывать её из
    трекера нельзя, даже когда токен это позволяет.
    """
    return source.direction == SOURCE_DIRECTION_READ_WRITE


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


def _secret_of(source: SignalSource) -> str:
    """
    Секрет источника: сначала введённый на сервере, потом окружение.

    Порядок именно такой. Введённое человеком важнее переменной, оставшейся на
    машине с прошлого выката: иначе смена токена через интерфейс молча ничего
    не меняла бы. Окружение остаётся запасным путём ради живого прода, который
    настроен так с первого среза.
    """
    if source.secret_ciphertext is not None:
        try:
            return decrypt_secret(source.secret_ciphertext)
        except SecretUnreadable as error:
            raise PollRefused("secret_unreadable", str(error)) from error
    return os.environ.get(source.credential_ref or "", "")


class Adapter(Protocol):
    """
    Чем читается источник: одна функция на провайдера.

    Протокол, а не тип из литерала словаря: `ADAPTERS` обязан быть однородным,
    и второй адаптер с другой сигнатурой должен краснеть здесь, а не в том
    месте, где его позвали. `full` обязателен у каждого — без него проба
    показывала бы «ничего нового» вместо «вот что видно».
    """

    async def __call__(
        self,
        source: SignalSource,
        transport: httpx.AsyncBaseTransport | None,
        *,
        full: bool = False,
    ) -> list[ExternalItem]: ...


async def _read_clickup(
    source: SignalSource,
    transport: httpx.AsyncBaseTransport | None,
    *,
    full: bool = False,
) -> list[ExternalItem]:
    """
    Открытые задачи личного воркспейса, изменённые после курсора.

    Токен читается из окружения по имени в `credential_ref`. Его отсутствие —
    отказ с машинным кодом, а не пустой список: «источник не настроен» и «у
    источника ничего нового» — разные ответы, и путать их нельзя.

    `full` снимает курсор: спрашивается всё открытое, а не изменившееся с
    прошлого раза. Так ходит проба (`probe_source`) — у источника, который уже
    читали, курсор отсекает всё старое, и «покажи, что видно» вернуло бы пустой
    список на прекрасно работающем ключе.
    """
    token = _secret_of(source)
    if not token:
        raise PollRefused(
            "no_credentials",
            "Токена нет. Задайте его на экране «Входящие» — он сохранится "
            "зашифрованным в строке источника.",
        )

    # ClickUp адресует воркспейс числовым id, а не именем аккаунта: `account`
    # в справочнике — это «личный» против «рабочего», человеческое различение,
    # и подставлять его в путь значит гарантированный 404 на первом же прогоне.
    team = str(source.settings.get("team_id") or "") or os.environ.get(
        CLICKUP_TEAM_ENV, ""
    )
    if not team:
        raise PollRefused(
            "no_workspace",
            "Не назван воркспейс: у ClickUp это числовой id, и взять его "
            "неоткуда. Впишите его рядом с токеном.",
        )

    params: dict[str, str] = {"subtasks": "true", "include_closed": "false"}
    since = None if full else source.cursor.get(CURSOR_UPDATED_MS)
    if since is not None:
        params["date_updated_gt"] = str(since)

    async with httpx.AsyncClient(
        transport=transport, timeout=POLL_TIMEOUT_SECONDS
    ) as client:
        try:
            response = await client.get(
                f"{CLICKUP_API}/team/{team}/task",
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


# Адаптер выбирается по **провайдеру**, а не по паре с аккаунтом: личный и
# рабочий ClickUp — это один и тот же API, разные токен и id воркспейса. Второй
# воркспейс должен быть данными, а не веткой в коде. Gmail и Telegram остаются
# заготовками до своих тикетов: экран показывает на них «адаптера нет», и poll
# в сеть не идёт.
ADAPTERS: dict[str, Adapter] = {"clickup": _read_clickup}


def _adapter_for(source: SignalSource) -> Adapter:
    """
    Чем читается этот источник, или отказ.

    Порядок отказов — от самого дешёвого к самому дорогому: выключенный
    источник и источник без адаптера не доходят до сети вовсе. Это не
    оптимизация, а свойство: «выключен» обязано означать, что наружу не ушло ни
    одного запроса, и оно одинаково у опроса и у пробы.
    """
    if not source.is_active:
        raise PollRefused(
            "source_disabled",
            "Источник выключен. Включите его прежде, чем читать.",
        )
    adapter = ADAPTERS.get(source.provider)
    if adapter is None:
        raise PollRefused(
            "no_adapter",
            f"У источника {source.provider}/{source.account} нет адаптера: "
            "строка в справочнике есть, читать её нечем.",
        )
    return adapter


async def probe_source(
    source: SignalSource,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[ExternalItem]:
    """
    Показать, что источник видит снаружи, ничего не записав.

    Отдельная операция, а не «опрос, только покажи». Опрос отвечает числами и
    двигает состояние: пишет сигналы, сдвигает курсор, ставит `last_polled_at`.
    После него вопрос «а ключ-то рабочий» тем же способом уже не задать —
    второй опрос честно вернёт ноль нового, и ноль будет неотличим от поломки.

    Проба не берёт сессию базы вовсе, и это не экономия, а граница: функции без
    сессии нечем записать даже по недосмотру. Курсор снимается (`full=True`),
    поэтому дважды нажатая кнопка дважды покажет одно и то же.

    Отказы те же и с теми же кодами, что у опроса, — включая главный: у
    выключенного источника наружу не уходит ни одного запроса.
    """
    adapter = _adapter_for(source)
    return await adapter(source, transport, full=True)


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
    adapter = _adapter_for(source)

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
