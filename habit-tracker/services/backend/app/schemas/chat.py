# [review:need-review] PHASE-03/111, PHASE-03/112, PHASE-03/113, PHASE-03/117
# summary: wire types of the chat — a conversation created with the day it belongs to, the feed item, one message as it is read back, the body of a turn, and the one flag that says whether the next turn continues a CLI session or rebuilds the dialogue; the SSE events are described here as constants so the frontend parser and the server cannot drift
# summary: PHASE-03/117 hangs the usage rollup on the feed item, so the header of a conversation can show what the subscription is spending before the first 429 does
# summary: PHASE-03/113 adds ConversationContext — the day card as it went into the prompt, its size, and which sections the ceiling ate
"""
Типы провода для чата.

**События потока названы здесь, а не в обработчике.** `delta`, `usage`, `done`,
`error` — четыре имени, которые обязаны совпадать у сервера и у разборщика во
фронте. Константа в схеме позволяет тесту сравнить порядок событий с именами, а
не с литералами, размазанными по коду.

Планы и выборки в этот срез не входят (`#114`, `#115`): ответ читается лентой
сообщений, и `GET /conversations/{id}` отдаёт только их.

**Карточка дня едет отдельной ручкой, а не полем сообщения.** Она про день, а
не про ход: класть её копию в каждое сообщение значило бы хранить один и тот же
текст столько раз, сколько было реплик.

**Расход едет в обеих ручках, а не только в детальной.** Лента показывает, во
что обошёлся каждый разговор, — иначе «дорогой» разговор виден лишь после того,
как в него зашли, а до первого 429 такой обход никто не сделает.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.chat import CONVERSATION_KIND_GENERAL

# Имена событий SSE. Порядок в норме: сколько угодно `delta`, затем `usage`,
# затем ровно один `done`; `error` заменяет два последних.
SSE_EVENT_DELTA = "delta"
SSE_EVENT_USAGE = "usage"
SSE_EVENT_DONE = "done"
SSE_EVENT_ERROR = "error"

# Потолок длины реплики. Не вкусовой: реплика уходит в промпт целиком, и
# мегабайт, вставленный в поле ввода, — это ход, который не закончится.
MESSAGE_MAX_CHARS = 20_000

# Потолок ленты за один запрос.
FEED_MAX_LIMIT = 200


class ConversationCreate(BaseModel):
    """Тело `POST /chat/conversations`."""

    started_on: date | None = Field(
        default=None,
        description=(
            "День, к которому привязан разговор. По умолчанию — сегодняшний по "
            "границе суток приложения, а не по календарю браузера."
        ),
    )
    kind: str = Field(
        default=CONVERSATION_KIND_GENERAL,
        description="`general` | `day_open` | `day_close`",
    )
    title: str | None = Field(default=None, max_length=200)


class ConversationUsage(BaseModel):
    """
    Расход подписки на один разговор.

    Три счётчика, а не один: прочитанный из кеша токен стоит иначе, чем
    свежий входной, и сумма «всего токенов» скрыла бы ровно тот эффект, ради
    которого расход и показывается — второй ход дешевле первого.

    `latency_ms_median` пуст у разговора, в котором ни один ход не замерялся.
    """

    model_config = ConfigDict(from_attributes=True)

    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    message_count: int
    latency_ms_median: int | None


class ConversationResponse(BaseModel):
    """Разговор в ленте: чем отвечали, когда трогали и во что он обошёлся."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str | None
    started_on: date
    kind: str
    llm_backend: str | None
    context_version: int
    last_message_at: datetime | None
    archived: bool
    created_at: datetime
    usage: ConversationUsage


class MessageResponse(BaseModel):
    """
    Одно сообщение.

    `error_code` машинный и приезжает наружу нарочно: экран показывает «ход не
    удался» вместе с причиной, а причина не должна быть куском текста модели.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    seq: int
    role: str
    content: str
    status: str
    error_code: str | None
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    latency_ms: int | None
    model: str | None
    created_at: datetime


class ConversationDetail(ConversationResponse):
    """Разговор вместе с сообщениями — то, что рисует экран после перезагрузки."""

    messages: list[MessageResponse]
    resume_ready: bool = Field(
        description=(
            "Продолжит ли следующий ход сессию CLI (`--resume`) или пересоберёт "
            "разговор из таблицы целиком. Считается на месте: сессия могла "
            "исчезнуть с диска между двумя ходами. Ответ разговора от этого не "
            "меняется — меняется его цена."
        )
    )


class MessageCreate(BaseModel):
    """Тело хода: одна реплика человека."""

    content: str = Field(min_length=1, max_length=MESSAGE_MAX_CHARS)


class ConversationContext(BaseModel):
    """
    Что чат видит: карточка дня ровно тем текстом, каким она ушла в промпт.

    `text` не пересказ и не выжимка — иначе раскрывашка отвечала бы на вопрос
    «что модель могла увидеть» вместо «что она увидела». `dropped_sections`
    называет секции, у которых потолок съел строки, в порядке выбывания.
    """

    conversation_id: int
    entry_date: date
    text: str
    chars: int
    max_chars: int
    truncated: bool
    dropped_sections: list[str]
