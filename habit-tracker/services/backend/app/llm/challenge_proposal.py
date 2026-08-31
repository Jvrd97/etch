# [review:need-review] PHASE-03/129
# summary: the model's answer turned into challenge proposals — the JSON shape it must emit, the semantic check that every rule points at a real (category, field) pair of the right type, and the write path that stores them as `origin='ai'`, `status='proposed'` and nothing else
"""
Челлендж, предложенный моделью.

**Модель не пишет в базу.** Она отвечает данными; данные разбираются здесь,
проверяются по существующим категориям и ложатся как предложение. Обязательство
на себя берёт человек, нажимая «принять», — тот же контракт, что у разбора дня
и применения плана (ADR-0005), а не второй параллельный механизм.

**Проверка не доверяет промпту.** Промпт просит модель ссылаться только на
существующие категории и поля; проверка исходит из того, что она этого не
сделала. Предложение, ссылающееся на несуществующую пару, отклоняется на
разборе — до того, как из него получится строка, которую человеку предъявят
кнопкой «принять».

**Заголовков в логах нет.** Человек называет челлендж диагнозом («месяц без
обезболивающих»), поэтому заголовок предложения попадает под то же правило,
что тексты в `transcripts`: логируются идентификаторы и счётчики.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field as PydanticField
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.challenge.rules import METRIC_RULE_KINDS
from app.crud import challenge as challenge_crud
from app.llm.plan_flow import PlanError, parse_json_plan
from app.models.category import Category
from app.models.challenge import Challenge
from app.models.field import FieldType
from app.schemas.challenge import ChallengeIn, FailureMode, RuleKind

logger = logging.getLogger(__name__)

# Типы полей, по которым правило умеет считать. `checked` и `abstain` живут на
# флажке, `metric_*` — на числе.
NUMERIC_FIELD_TYPES: tuple[FieldType, ...] = (FieldType.NUMBER, FieldType.DURATION)

UNKNOWN_PAIR = (
    "предложение {index}: поля {field_id} нет в категории {category_id} — "
    "правило по чужому полю всегда считало бы пустой день"
)
WRONG_FIELD_TYPE = (
    "предложение {index}: правилу {rule_kind!r} не подходит поле {field_id} "
    "типа {field_type!r}"
)

CHALLENGE_PROPOSAL_PROMPT = """\
You propose habit challenges from what the person has been logging.

You emit ONLY a JSON object, no prose, no markdown fences, of the shape:
{
  "proposals": [
    {
      "title": "<short, in the person's own language>",
      "category_id": <id of an existing category>,
      "field_id": <id of a field of THAT category>,
      "rule_kind": "metric_at_least" | "metric_at_most" | "checked" | "abstain",
      "target": <number, only for metric_at_least / metric_at_most>,
      "starts_on": "YYYY-MM-DD",
      "ends_on": "YYYY-MM-DD",
      "failure_mode": "any_miss" | "budget",
      "allowed_misses": <integer, only meaningful with "budget">
    }
  ]
}

Rules:
- Only existing category and field ids. The field MUST belong to the category.
- `metric_*` rules need a numeric field and a `target`; `checked` and `abstain`
  need a boolean field and no `target`.
- `abstain` belongs to an avoid category, `checked` to a build one.
- Never emit a status or an origin: a proposal is a proposal.
- Propose at most three at a time. An empty list is a valid answer.
- Output must be valid JSON and nothing else."""


class ChallengeProposalError(PlanError):
    """Ответ модели не разобрался или не прошёл смысловую проверку."""


class ProposedChallenge(BaseModel):
    """Одно предложение, каким его прислала модель."""

    model_config = ConfigDict(extra="forbid")

    title: str = PydanticField(..., min_length=1, max_length=200)
    category_id: int
    field_id: int
    rule_kind: RuleKind
    target: Decimal | None = None
    starts_on: date
    ends_on: date
    failure_mode: FailureMode = "any_miss"
    allowed_misses: int = 0

    def as_challenge(self) -> ChallengeIn:
        """
        Предложение как обычное тело `POST /challenges`.

        Второго набора правил про окно и порог не заводится: `ChallengeIn`
        уже отказывает окну назад, окну длиннее потолка и порогу не у того
        правила, и отказывает всем писателям одинаково.
        """
        return ChallengeIn(
            title=self.title,
            category_id=self.category_id,
            field_id=self.field_id,
            rule_kind=self.rule_kind,
            target=self.target,
            starts_on=self.starts_on,
            ends_on=self.ends_on,
            failure_mode=self.failure_mode,
            allowed_misses=self.allowed_misses,
            # Литералами, а не константами модели: `ChallengeIn` типизирован
            # `Literal`, и константа-строка тут ничего не выигрывает, кроме
            # `type: ignore`. Правило «машинный источник → предложение»
            # держится проверкой в самой схеме, не этими двумя значениями.
            origin="ai",
            status="proposed",
        )


class ChallengeProposals(BaseModel):
    """Весь ответ модели: список предложений, возможно пустой."""

    model_config = ConfigDict(extra="forbid")

    proposals: list[ProposedChallenge] = PydanticField(default_factory=list)


def parse_proposals(text: str) -> ChallengeProposals:
    """Сырой текст модели → предложения (проверка формы, не смысла)."""
    return parse_json_plan(text, ChallengeProposals, ChallengeProposalError)


def _fits(rule_kind: str, field_type: FieldType) -> bool:
    """Умеет ли правило считать по такому полю."""
    if rule_kind in METRIC_RULE_KINDS:
        return field_type in NUMERIC_FIELD_TYPES
    return field_type is FieldType.BOOLEAN


def validate_proposals(
    proposals: ChallengeProposals, categories: Sequence[Category]
) -> None:
    """
    Смысловая проверка поверх формы: пары `(категория, поле)` существуют и
    правило по такому полю считается.

    Ошибки собираются все сразу — один заход починки видит их разом, ровно как
    в разборе онбординга. Тексты ошибок называют идентификаторы, а не
    заголовки: сообщение об отказе тоже читается людьми и попадает в ответ.
    """
    fields_by_category: dict[int, dict[int, FieldType]] = {
        category.id: {field.id: field.field_type for field in category.fields}
        for category in categories
    }
    errors: list[str] = []

    for index, proposal in enumerate(proposals.proposals, start=1):
        own = fields_by_category.get(proposal.category_id, {})
        field_type = own.get(proposal.field_id)
        if field_type is None:
            errors.append(
                UNKNOWN_PAIR.format(
                    index=index,
                    field_id=proposal.field_id,
                    category_id=proposal.category_id,
                )
            )
            continue
        if not _fits(proposal.rule_kind, field_type):
            errors.append(
                WRONG_FIELD_TYPE.format(
                    index=index,
                    rule_kind=proposal.rule_kind,
                    field_id=proposal.field_id,
                    field_type=field_type.value,
                )
            )

    if errors:
        raise ChallengeProposalError("; ".join(errors))


async def load_categories(db: AsyncSession) -> Sequence[Category]:
    """Категории с их полями — контекст промпта и материал проверки."""
    result = await db.execute(select(Category).where(Category.is_active.is_(True)))
    categories = list(result.scalars().unique().all())
    for category in categories:
        await db.refresh(category, ["fields"])
    return categories


async def store_proposals(
    db: AsyncSession, proposals: ChallengeProposals
) -> list[Challenge]:
    """
    Сохранить проверенные предложения — и ничего, кроме предложений.

    Статус ставится здесь, а не берётся из данных модели: `ChallengeIn`
    отказывает машинному источнику в `active`, а `initial_status()` возвращает
    `proposed` вне зависимости от присланного. Двух способов завести
    предложение не существует.
    """
    stored: list[Challenge] = []
    for proposal in proposals.proposals:
        body = proposal.as_challenge()
        stored.append(
            await challenge_crud.create_challenge(
                db,
                title=body.title,
                category_id=body.category_id,
                field_id=body.field_id,
                rule_kind=body.rule_kind,
                target=body.target,
                starts_on=body.starts_on,
                ends_on=body.ends_on,
                failure_mode=body.failure_mode,
                allowed_misses=body.allowed_misses,
                origin=body.origin,
                status=body.initial_status(),
            )
        )
    # Только счётчик и идентификаторы: заголовок челленджа — то, что человек
    # про себя обещал, и в логе ему делать нечего.
    logger.info(
        "stored %s challenge proposals: %s",
        len(stored),
        [challenge.id for challenge in stored],
    )
    return stored


def describe_categories(categories: Sequence[Category]) -> str:
    """Компактный контекст для промпта: id, имена, поля с типами."""
    if not categories:
        return "(none yet)"
    lines: list[str] = []
    for category in categories:
        fields = ", ".join(
            f"{field.id}:{field.name}:{field.field_type.value}"
            for field in category.fields
        )
        lines.append(
            f"- id={category.id} name={category.name!r} "
            f"streak_mode={category.streak_mode} fields=[{fields}]"
        )
    return "\n".join(lines)


def build_prompt(categories: Sequence[Category], context: str) -> str:
    """Промпт целиком: правила ответа, существующие категории, наблюдение."""
    return (
        f"{CHALLENGE_PROPOSAL_PROMPT}\n\n"
        f"## Existing categories\n{describe_categories(categories)}\n\n"
        f"## What the person has been logging\n{context}"
    )


__all__ = [
    "CHALLENGE_PROPOSAL_PROMPT",
    "ChallengeProposalError",
    "ChallengeProposals",
    "ProposedChallenge",
    "build_prompt",
    "describe_categories",
    "load_categories",
    "parse_proposals",
    "store_proposals",
    "validate_proposals",
]
