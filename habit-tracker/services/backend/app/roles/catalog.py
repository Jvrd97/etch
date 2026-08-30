# [review:need-review] PHASE-03/134
# summary: seed rows of the role directory — cto/architect/techlead/unassigned with the 25/25/50 target shares carried as a hypothesis
"""
Seed rows of the role directory.

Four roles, from the job description: CTO (strategy, roadmap, stack, budget,
hiring, the report upwards), architect (services, events, the data model, the
safety of medical data, ADRs), tech lead (review, standards, CI, own code) —
plus `unassigned`, which exists so that work nobody could attribute has a place
to be seen instead of a NULL to be missed.

`target_share_pct` here is a hypothesis about the quarter, not a norm the day is
scored against. It sums to a hundred across the three working roles because that
is what a share is, not because the split has been verified by anything.

The migration spells the same four rows out again rather than importing this
module: a migration that imports `app/` breaks the day `app/` is refactored, and
this list is what a database built by `create_all` (a test database, which never
sees the migration) starts from.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.role import (
    ROLE_CODE_ARCHITECT,
    ROLE_CODE_CTO,
    ROLE_CODE_TECHLEAD,
    ROLE_CODE_UNASSIGNED,
)


@dataclass(frozen=True)
class RoleSeed:
    code: str
    title: str
    description: str
    target_share_pct: int | None
    ord: int


SEED_ROLES: tuple[RoleSeed, ...] = (
    RoleSeed(
        code=ROLE_CODE_CTO,
        title="CTO",
        description=(
            "Стратегия, роадмап, стек, бюджет, найм, отчёт руководству, "
            "партнёры и инвесторы."
        ),
        target_share_pct=25,
        ord=1,
    ),
    RoleSeed(
        code=ROLE_CODE_ARCHITECT,
        title="Системный архитектор",
        description=(
            "Микросервисы, событийное взаимодействие, модель данных, "
            "безопасность медданных, ADR."
        ),
        target_share_pct=25,
        ord=2,
    ),
    RoleSeed(
        code=ROLE_CODE_TECHLEAD,
        title="Тимлид",
        description=(
            "Code review, стандарты качества, CI/CD, собственный код на "
            "Python/FastAPI, iOS/Swift и вебе."
        ),
        target_share_pct=50,
        ord=3,
    ),
    RoleSeed(
        code=ROLE_CODE_UNASSIGNED,
        title="Не отнесено",
        # Working time all the same — hence `is_work` stays true for this row
        # too. What it lacks is a name, not a claim on the day.
        description="Работа, которую не удалось отнести ни к одной роли.",
        # No target: aiming at a share of unattributed work is aiming at the
        # wrong thing. The number to move is this one, downward, by writing a
        # rule.
        target_share_pct=None,
        ord=9,
    ),
)

__all__ = ["SEED_ROLES", "RoleSeed"]
