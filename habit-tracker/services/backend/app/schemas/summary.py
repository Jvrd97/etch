# [review:need-review] PHASE-03/90
# summary: wire types of the day's итог — what closing a day sends (an override refused without its note) and what the day answers with, including the live block an unclosed day gets
"""
Wire types of the итог of a day.

**Закрытие дня — один документ, но пишутся только названные поля.** The verdict
is a property of the whole day: the minutes of work, the prose and the override
are read together or the answer is wrong, and a handle per field would let a day
be half closed with nothing saying so. What the shape of the document must not
mean is «всё, что не прислали, обнулить»: the same handle closes a day and later
переопределяет its verdict with two fields, so `app.crud.summary` writes by
`model_fields_set` and an absent field leaves the stored value alone.

**Переопределение без записки не проходит валидатор — и не проходит базу.** The
validator here is the message a person reads; the CHECK on `day_summary` is the
rule. Both exist because the rule has to hold for a writer that never sees this
schema.

**`missing_data` и `verdict_reason` — машинные коды.** The Russian a person
reads lives in `lib/day-format.ts`, exactly as it does for `mark.state`: one
vocabulary in the database, one translation on the screen, no прозы в колонке.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.day.evaluate import VERDICTS


class DayCloseIn(BaseModel):
    """
    What closing a day says about it — the fields named, and only those.

    Every field carries a default, and every default means «не прислали», not
    «обнулить»: the writer reads `model_fields_set`. Sending
    `verdict_override: false` is therefore how an override is removed, and
    leaving the field out is how it survives.
    """

    model_config = ConfigDict(extra="forbid")

    work_minutes: int | None = Field(
        None,
        ge=0,
        description=(
            "Минуты работы за день. null — не измерено, а не ноль: проверка "
            "переработки пропускается, а факт уходит в `missing_data`"
        ),
    )
    body_md: str = Field(
        "",
        description=(
            "Проза итога — «что случилось вместо плана», «что мешало». Ищется по тексту"
        ),
    )

    wrote_from_scratch: int | None = Field(
        None, ge=0, description="Минуты, написанные с нуля без ИИ; null — не спрашивали"
    )
    education_debt: int | None = Field(
        None, ge=0, description="Сколько вопросов Education висит неразобранными"
    )
    reviewed_today: int | None = Field(
        None, ge=0, description="Сделано ли ревью дня; null — не спрашивали"
    )

    verdict_override: bool = Field(
        False,
        description=(
            "Человек говорит «день был выигран, просто я не отметил». Требует "
            "записки; машинная причина остаётся видимой"
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
    """

    day_date: date
    closed: bool = Field(
        ..., description="Есть ли строка итога. false — идёт живой пересчёт"
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
