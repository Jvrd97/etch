# [review:need-review] PHASE-03/111, PHASE-03/112, PHASE-03/113, PHASE-03/115, PHASE-03/116, PHASE-03/117, PHASE-03/187
# summary: wire types of the chat — a conversation created with the day it belongs to, the feed item, one message as it is read back, the body of a turn, the one flag that says whether the next turn continues a CLI session or rebuilds the dialogue, and `ChatPlan`, whose whole point is which operations it cannot express; the SSE events are described here as constants so the frontend parser and the server cannot drift
# summary: PHASE-03/117 hangs the usage rollup on the feed item, so the header of a conversation can show what the subscription is spending before the first 429 does
# summary: PHASE-03/113 adds ConversationContext — the day card as it went into the prompt, its size, and which sections the ceiling ate
# summary: PHASE-03/115 grows a fourth operation — ChatDayPlanOp, a whole day plan the chat may propose for a day that has none, reusing the sections and items of `#148` and carrying no field with which an existing plan could be named, let alone replaced
# summary: PHASE-03/187 opens that fourth operation to a day that already has a plan — `op` now names either a draft or a rewrite, the server decides which by the state of the day, and marks survive a rewrite through the codes the lines come back with
"""
Типы провода для чата.

**События потока названы здесь, а не в обработчике.** `delta`, `usage`, `done`,
`error` — четыре имени, которые обязаны совпадать у сервера и у разборщика во
фронте. Константа в схеме позволяет тесту сравнить порядок событий с именами, а
не с литералами, размазанными по коду.

Выборки в этот срез не входят (`#114`). План (`#115`) входит: `ChatPlan` — это
объединение операций, которые чат вправе предложить, и его содержание целиком
про то, каких операций в нём нет.

**Карточка дня едет отдельной ручкой, а не полем сообщения.** Она про день, а
не про ход: класть её копию в каждое сообщение значило бы хранить один и тот же
текст столько раз, сколько было реплик.

**Расход едет в обеих ручках, а не только в детальной.** Лента показывает, во
что обошёлся каждый разговор, — иначе «дорогой» разговор виден лишь после того,
как в него зашли, а до первого 429 такой обход никто не сделает.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.chat import CONVERSATION_KIND_GENERAL
from app.schemas.daily_summary import CheckOp, JournalOp, LogMetricOp
from app.schemas.day_plan import GeneratedDayPlan, GeneratedSection

# Имена событий SSE. Порядок в норме: сколько угодно `delta`, затем `usage`,
# затем ровно один `done`; `error` заменяет два последних.
SSE_EVENT_DELTA = "delta"
SSE_EVENT_USAGE = "usage"
SSE_EVENT_DONE = "done"
SSE_EVENT_ERROR = "error"
# Кадр именованной выборки (`#114`). Отдельное событие, а не `delta`: строка
# «запрошено сон за 14 дней» — это не текст ответа, и подмешивать её в пузырь
# значило бы вписывать в слова модели то, чего она не говорила.
SSE_EVENT_RETRIEVAL = "retrieval"

# Потолок длины реплики. Не вкусовой: реплика уходит в промпт целиком, и
# мегабайт, вставленный в поле ввода, — это ход, который не закончится.
MESSAGE_MAX_CHARS = 20_000

# Потолок ленты за один запрос.
FEED_MAX_LIMIT = 200

# Отказ на плане, который ничего не предлагает.
EMPTY_PLAN = (
    "план не несёт ни одной операции: ответ без операций — это сообщение, "
    "а не предложение"
)


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
    # Плашка под сообщением, если модель что-то предложила. Заполняется ручкой
    # разговора: у самой строки `chat_messages` такого столбца нет — план живёт
    # своей таблицей и своим жизненным циклом.
    plan_id: int | None = None
    # Что модель достала, отвечая этим сообщением. Пустой список — обычный
    # случай: карточки дня хватило, и наружу за данными никто не ходил.
    retrievals: list["ChatRetrievalResponse"] = Field(default_factory=list)


class ChatRetrievalResponse(BaseModel):
    """
    Одна именованная выборка так, как её видит экран.

    Данных здесь нет — имя, параметры и размер. Строка под ответом отвечает на
    вопрос «какие мои данные ушли», не заставляя открывать ни базу, ни сами
    данные, и это единственное, ради чего таблица существует.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    query_name: str
    params: dict[str, Any]
    row_count: int
    chars: int
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


class ChatJournalOp(JournalOp):
    """
    Текст дня, каким его вправе предложить чат: дописать или создать, не заменить.

    `JournalOp` экрана разбора дня допускает `mode="replace"` — режим, который
    теряет уже написанное. Тот экран его не выбирает, но *может* выразить, и для
    одноходового разбора это терпимо. Здесь нет: замена текста дня — операция
    класса W2, и в плане чата её не должно быть не по договорённости, а по
    типам. `replace` вычеркнут из `mode`, поэтому модель, ответившая мимо
    инструкции, всё равно не сможет сказать слова, которого нет.

    Проверяется это `tests/test_chat_plan_schema.py`: он обходит имена всей
    схемы и падает на любом, которым можно сказать «замени».
    """

    model_config = ConfigDict(extra="ignore")

    mode: Literal["append", "create"] = "append"


# Как называется операция плана дня в каждом из двух состояний дня. Имена
# разные, потому что человек нажимает на разное: черновик заполняет пустой день,
# перезапись стирает то, что там стояло, и плашка обязана сказать какое именно.
DayPlanOpName = Literal["draft_day_plan", "rewrite_day_plan"]
DAY_PLAN_OP_DRAFT: DayPlanOpName = "draft_day_plan"
DAY_PLAN_OP_REWRITE: DayPlanOpName = "rewrite_day_plan"


class ChatDayPlanOp(BaseModel):
    """
    План дня, каким его вправе предложить чат: собрать пустой день или переписать
    занятый.

    **Словарь строк переиспользован, а не написан рядом.** `GeneratedSection` и
    `GeneratedItem` — та же форма, которой отвечает модель ручке
    `POST /day/{on}/plan/generate`, и те же две конверсии (`to_draft` для восьми
    ограничений, `to_document` для единственного пути записи). Второй словарь
    строк означал бы второе место, где можно случайно завести операцию, которой
    здесь быть не должно.

    **Перезапись — единственная операция класса W2 в правах чата.** Открыта она
    нарочно и с названными последствиями: план дня целиком заменяем и с экрана
    дня, а разговор был единственным местом, откуда день нельзя было пересобрать
    словами. Всё остальное из W2 — снять отметку, удалить строку, переименовать
    категорию — по-прежнему невыразимо: в схеме нет ни поля, ни значения, которым
    это можно сказать.

    **Плана дня целиком — да, его куска — нет.** Полей, которыми можно указать на
    одну строку существующего плана, здесь нет: ни её id, ни её кода отдельно от
    нового состава. Правка по строке — действие экрана дня, где она пишет журнал
    и не режет ревизию; из разговора день переписывается целиком или никак.

    **Имя операции ставит сервер, а не модель.** Есть ли на дне план — это факт
    базы, а не часть пересказа, и модель вправе в нём ошибиться. Ответ приходит
    с любым из двух имён, а в `chat_plans` ложится то, которое соответствует
    состоянию дня на момент рождения предложения; перед записью день проверяется
    ещё раз.

    **Отметки переживают перезапись по кодам.** `replace_plan` поднимает отметки
    строк, чьи id вернулись в документе, а id строки — это `uuid5` от её кода
    (`app.schemas.day_plan.ITEM_NAMESPACE`). Строка, чей код в новом плане тот же,
    остаётся той же строкой; строка с новым кодом — новая и без отметки. Поэтому
    коды существующего плана и попадают в карточку дня: без них модель не может
    сохранить прожитый день, даже если хочет.
    """

    model_config = ConfigDict(extra="forbid")

    op: DayPlanOpName = DAY_PLAN_OP_DRAFT
    title: str | None = None
    sections: list[GeneratedSection] = Field(default_factory=list)

    @property
    def rewrites(self) -> bool:
        """Сотрёт ли применение то, что на дне уже стоит."""
        return self.op == DAY_PLAN_OP_REWRITE

    def named_by(self, *, day_taken: bool) -> "ChatDayPlanOp":
        """
        Та же операция под именем, которое соответствует состоянию дня.

        Копия, а не правка на месте: предложение уходит в `chat_plans` целиком, и
        менять его после сохранения было бы вторым источником правды о том, на
        что человек нажимал.
        """
        wanted: DayPlanOpName = DAY_PLAN_OP_REWRITE if day_taken else DAY_PLAN_OP_DRAFT
        if self.op == wanted:
            return self
        return self.model_copy(update={"op": wanted})

    def as_generated(self) -> GeneratedDayPlan:
        """Предложение в той форме, которую уже умеют обе конверсии `#148`."""
        return GeneratedDayPlan(title=self.title, sections=list(self.sections))

    def item_count(self) -> int:
        """Сколько строк несёт предложенный день."""
        return sum(len(section.items) for section in self.sections)


class ChatPlan(BaseModel):
    """
    Что чат предлагает записать — и ничего сверх этого.

    **Несущее свойство схемы — чего в ней нет.** Права разведены на три класса:
    R (сервер читает сам), W1 (добавление без потерь — отметка, метрика, текст
    дня), W2 (снять отметку, переписать, удалить, переименовать). W2 не
    запрещён текстом промпта, а **невыразим в типах**: в объединении операций
    нет ни снятия отметки, ни удаления, ни переименования — ровно так же, как в
    `CheckOp` физически нет поля `value`.

    Модель, ответившая мимо инструкции, всё равно не сможет сказать слова,
    которого нет в схеме. Проверяется это тестом на JSON Schema
    (`tests/test_chat_plan_schema.py`), а не прогоном промпта: промпт — это
    просьба, схема — это граница.

    Операции взяты у экрана разбора дня целиком (`app.schemas.daily_summary`), а
    не переписаны рядом. Второй словарь операций означал бы второе место, где
    можно случайно добавить W2.

    Четвёртая операция — план дня (`day_plan`). Она про другой объект и пишется
    другим путём (`replace_plan`, а не `apply_daily_summary`), поэтому и стоит
    отдельным полем, а не втискивается в `metrics`.

    **Из W2 в объединении есть ровно одна операция — перезапись плана дня.**
    Открыта она названным решением, а не по недосмотру: план дня и так заменяем
    целиком с экрана дня, а разговор был единственным местом, откуда день нельзя
    было пересобрать словами. Стоит она на трёх ограничителях: заменяется весь
    план и никогда его кусок, применяет её человек тапом по плашке, а отметки
    переносятся по кодам строк. Остальной W2 — снятие отметки, удаление строки,
    переименование категории — по-прежнему невыразим, и тест схемы падает на
    любом имени, которым это можно было бы сказать.
    """

    model_config = ConfigDict(extra="forbid")

    entry_date: date
    metrics: list[LogMetricOp] = Field(default_factory=list)
    checklist: list[CheckOp] = Field(default_factory=list)
    journal: ChatJournalOp | None = None
    day_plan: ChatDayPlanOp | None = None

    @model_validator(mode="after")
    def _must_propose_something(self) -> ChatPlan:
        """
        План без единой операции — это не план, а обычная реплика.

        Разница видна на экране: пустой план нарисовал бы плашку с кнопкой
        «применить», которая ничего не применяет. Такой ответ модели — просто
        сообщение без плашки, и отказ здесь и есть способ им стать.
        """
        if (
            not self.metrics
            and not self.checklist
            and self.journal is None
            and self.day_plan is None
        ):
            raise ValueError(EMPTY_PLAN)
        return self

    def operation_count(self) -> int:
        """
        Сколько операций план предлагает — число под плашкой.

        План дня считается одной операцией, а не двадцатью строками: он и
        применяется целиком. Половина плана нарушает канон почти всегда, и
        «применено 14 из 20» было бы обещанием, которого выполнить нельзя.
        """
        return (
            len(self.metrics)
            + len(self.checklist)
            + (1 if self.journal else 0)
            + (1 if self.day_plan else 0)
        )


class ChatPlanApply(BaseModel):
    """
    Что человек оставил отмеченным, когда нажал «применить».

    Клиент присылает подмножество предложенного, а не свой набор операций:
    сервер сверяет каждую с сохранённым планом и отказывает на всём, чего в
    плане не было. Иначе плашка была бы просто ещё одним путём записи в базу, а
    `chat_plans` не доказывал бы, что применено ровно показанное.

    `entry_date` здесь нет намеренно: дату несёт сохранённый план. Дата в теле
    позволила бы применить вчерашнее предложение к сегодняшнему дню — тихо и
    без следа.
    """

    model_config = ConfigDict(extra="forbid")

    metrics: list[LogMetricOp] = Field(default_factory=list)
    checklist: list[CheckOp] = Field(default_factory=list)
    journal: ChatJournalOp | None = None
    day_plan: bool = Field(
        default=False,
        description=(
            "Брать ли предложенный план дня. Флаг, а не подмножество секций: "
            "план применяется целиком или никак"
        ),
    )


class ChatPlanResponse(BaseModel):
    """
    План так, как его читает плашка и лента.

    `plan` отдаётся ровно тем, что лежит в `chat_plans.plan`: план, показанный
    два хода назад, обязан открываться тем же, чем был.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    message_id: int
    entry_date: date
    status: str
    plan: ChatPlan
    operation_count: int
    applied_summary_id: int | None
    applied_at: datetime | None
    created_at: datetime


class ChatPlanApplyResponse(BaseModel):
    """
    Что записало применение — и сколько операций оно закрыло.

    `day_plan_id` пуст у применения, которое плана дня не касалось. Идентификатор,
    а не «да/нет»: по нему открывается записанный план и его первая ревизия, и без
    него ответ не отличает «план записан» от «план был и его не тронули».
    """

    plan: ChatPlanResponse
    entry_ids: list[int]
    journal_entry_id: int | None = None
    day_plan_id: uuid.UUID | None = None
    applied_operations: int


class ResetResponse(BaseModel):
    """
    Ответ ручки сброса: сколько зависших ходов расклинено.

    Число, а не 204: ноль и единица здесь означают разное. Ноль — диалог и так
    был свободен, и человеку незачем ждать, что «теперь заработает».
    """

    reset: int = Field(ge=0, description="Сколько ходов переведено в `interrupted`")
