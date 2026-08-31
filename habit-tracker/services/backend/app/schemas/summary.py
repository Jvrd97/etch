# [review:need-review] PHASE-03/90, PHASE-03/143
# summary: wire types of the day's итог — what the 15:40 touch sends, what the evening touch sends (an override refused without its note), and what the day answers with, including the stage of closing and the `review_skipped` a day closed in one touch carries
"""
Wire types of the итог of a day.

**Каждое касание — один документ, а не поле за полем.** The verdict is a
property of the whole day: the minutes of work, the prose and the override are
read together or the answer is wrong, and a PATCH-shaped API would let a day be
half closed with nothing saying so. Half-closed is a *stage* — a different
statement — and оно названо на строке, а не выведено из того, какие поля
случайно заполнены.

**`null` в теле — «не трогать», а не «стереть».** Касаний два, и второе не
обязано повторять то, что записало первое: вечернее закрытие, не назвавшее
рабочие минуты, оставляет цифру, пришедшую в 15:40. Стереть записанное значение
через API нельзя, и это осознанно: `work_minutes` всё равно пересчитывается по
интервалам дня (`#91`), а прозу правят, а не обнуляют.

**Вердикта в теле приёма нет ни у одного касания.** Он вычисляется чистой
функцией `evaluate_day`; клиент не может ни прислать его, ни попросить.
`extra="forbid"` превращает попытку в 422, а не в молчаливо проигнорированное
поле.

**Переопределение без записки не проходит валидатор — и не проходит базу.** The
validator here is the message a person reads; the CHECK on `day_summary` is the
rule. Both exist because the rule has to hold for a writer that never sees this
schema.

**`missing_data` и `verdict_reason` — машинные коды.** The Russian a person
reads lives in `lib/day-format.ts`, exactly as it does for `mark.state`: one
vocabulary in the database, one translation on the screen, no прозы в колонке.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.day.evaluate import VERDICTS
from app.models.summary import (
    ORIGIN_NONE,
    STAGE_OPEN,
    SUMMARY_STAGES,
    VERDICT_ORIGINS,
)


class DayReviewIn(BaseModel):
    """
    Касание около 15:40: факт по рабочим задачам и рабочие минуты.

    Отметки пунктов сюда не едут — они уже записаны через `PUT
    /day/{date}/marks/{item_id}`, и второй путь для того же факта означал бы два
    ответа на вопрос «сделана ли задача W2». Здесь остаётся то, чему в дне
    больше негде лежать: сколько наработано и три вопроса, которые задаёт
    рабочая часть закрытия.

    Вердикта это касание не выносит. `stage` становится `reviewed`, `verdict`
    остаётся NULL, и на экране это «вердикт будет вечером», а не «день
    проигран».
    """

    model_config = ConfigDict(extra="forbid")

    work_minutes: int | None = Field(
        None,
        ge=0,
        description=(
            "Минуты работы к моменту ревью. null — не трогать записанное; "
            "измерение по `work_interval` всё равно сильнее этой цифры"
        ),
    )
    body_md: str | None = Field(
        None,
        description="Черновик разбора. null — не трогать уже написанное",
    )

    wrote_from_scratch: int | None = Field(
        None, ge=0, description="Минуты, написанные с нуля без ИИ; null — не трогать"
    )
    education_debt: int | None = Field(
        None, ge=0, description="Сколько вопросов Education висит неразобранными"
    )
    reviewed_today: int | None = Field(
        None, ge=0, description="Сделано ли ревью дня; null — не трогать"
    )


class DayCloseIn(BaseModel):
    """
    Вечернее касание: якоря, вердикт, стрик — то, чем день закрывается.

    Оно же принимается устаревшей ручкой `POST /day/{date}/close`, потому что
    это ровно тот документ, который она принимала до `#143`: одна схема, а не
    её копия под новым именем.
    """

    model_config = ConfigDict(extra="forbid")

    work_minutes: int | None = Field(
        None,
        ge=0,
        description=(
            "Минуты работы за день. null — не трогать записанное; когда цифры "
            "нет нигде, день читается как «не измерено», а не как ноль: "
            "проверка переработки пропускается, а факт уходит в `missing_data`"
        ),
    )
    body_md: str | None = Field(
        None,
        description=(
            "Проза итога — «что случилось вместо плана», «что мешало». Ищется "
            "по тексту. null — не трогать написанное в 15:40"
        ),
    )

    wrote_from_scratch: int | None = Field(
        None, ge=0, description="Минуты, написанные с нуля без ИИ; null — не трогать"
    )
    education_debt: int | None = Field(
        None, ge=0, description="Сколько вопросов Education висит неразобранными"
    )
    reviewed_today: int | None = Field(
        None, ge=0, description="Сделано ли ревью дня; null — не трогать"
    )

    verdict_override: bool | None = Field(
        None,
        description=(
            "Человек говорит «день был выигран, просто я не отметил». Требует "
            "записки; машинная причина остаётся видимой. null — не трогать: "
            "перезакрытие дня не отменяет сделанного переопределения"
        ),
    )
    verdict_override_note: str | None = Field(
        None, description="Почему вердикт переопределён. Без неё переопределения нет"
    )

    @model_validator(mode="after")
    def _override_needs_a_note(self) -> DayCloseIn:
        """
        An override arrives with its note, and a note is never cleared alone.

        The second half exists because the write is partial: clearing the note
        of a row whose `verdict_override` is still true would leave the pair the
        `CHECK` forbids, and the reader would get a 500 for a rule the schema is
        supposed to state. Removing an override is `verdict_override: false`.
        """
        if self.verdict_override and not (self.verdict_override_note or "").strip():
            raise ValueError(
                "переопределение вердикта требует записки: "
                "verdict_override_note не может быть пустой"
            )
        sent = self.model_fields_set
        clears_note = (
            "verdict_override_note" in sent
            and not (self.verdict_override_note or "").strip()
        )
        if clears_note and "verdict_override" not in sent:
            raise ValueError(
                "записку переопределения нельзя стереть отдельно: "
                "снимайте переопределение полем verdict_override"
            )
        return self


class DaySummaryResponse(BaseModel):
    """
    The итог of a day as the screen reads it, closed or not.

    A day nobody closed gets this block too — a live recount with `closed:
    false`, `verdict: null` and the reason `not_closed`. One code path answers
    both, so «не закрыл» and «проиграл» differ by a field rather than by the
    shape of the response, and the screen can show progress before anything is
    pressed.

    `stage` splits «не закрыл» in two. `open` — никто не начинал; `reviewed` —
    касание 15:40 прошло, и `verdict: null` тут значит «рано», а не «проиграл».
    Экран читает подпись по стадии, а не по одному лишь пустому вердикту.
    """

    day_date: date
    closed: bool = Field(
        ...,
        description=(
            "Дошло ли закрытие до конца (`stage='closed'`). false — идёт живой "
            "пересчёт, и вердикта пока нет"
        ),
    )
    stage: str = Field(
        STAGE_OPEN,
        description=(
            f"Стадия закрытия: {' | '.join(SUMMARY_STAGES)}. `open` — никто не "
            "начинал, `reviewed` — было касание 15:40, вердикт будет вечером"
        ),
    )
    reviewed_at: datetime | None = Field(
        None, description="Когда прошло касание 15:40. null — его не было"
    )
    review_skipped: bool = Field(
        False,
        description=(
            "День закрыт одним касанием: ревью в 15:40 не случилось. Это "
            "обычный день, а не ошибка, — но отличимый"
        ),
    )
    rule_set_id: int = Field(
        ..., description="Правило, по которому день посчитан — канон меняется"
    )

    verdict: str | None = Field(
        None, description=f"Одно из: {', '.join(VERDICTS)}; null — день не закрыт"
    )
    verdict_reason: str = Field(
        "",
        description=(
            "Какое условие не выполнено: tasks | anchors | overtime | "
            "not_closed. Пусто — выполнены все"
        ),
    )
    verdict_override: bool = False
    verdict_override_note: str | None = None

    anchors_done: int
    anchors_total: int
    tasks_done: int
    tasks_total: int

    work_minutes: int | None = None
    streak_after: int | None = Field(
        None, description="Стрик выигранных дней после этого дня; null — день не закрыт"
    )

    wrote_from_scratch: int | None = None
    education_debt: int | None = None
    reviewed_today: int | None = None

    body_md: str = ""
    missing_data: list[str] = Field(
        default_factory=list, description="Чего не хватило для суждения, кодами"
    )
    missing_anchors: list[str] = Field(
        default_factory=list,
        description=(
            "Тексты неотмеченных якорей — расшифровка «какого именно якоря не "
            "хватило». Считается по плану и отметкам, в базе не хранится"
        ),
    )
    source: str = Field(
        "close", description="close — день закрыт здесь; import — вердикт пришёл прозой"
    )
    verdict_origin: str = Field(
        ORIGIN_NONE,
        description=(
            f"Откуда взялся вердикт: {' | '.join(VERDICT_ORIGINS)}. "
            "`migrated_prose` — перенесён из записи и пересчёту не подлежит; "
            "`none` — вердикта нет"
        ),
    )
