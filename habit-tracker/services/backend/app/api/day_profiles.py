# [review:need-review] PHASE-03/179
# summary: the endpoints of the breathing ceiling — the named profiles, the proposal that always carries its reason, the activation a person signs (the only thing that moves a ceiling) and the ledger of overtime debt; a separate router registered before /day/{date} so that /day/debt is a path and not a malformed date
"""
HTTP surface of the work-ceiling profiles and of the overtime debt.

Separate from `app.api.day` for two reasons, and the second is not cosmetic.

The first is size: the day router already answers for the plan, the marks, the
anchors, the training and the intervals.

The second is routing. `/day/debt` and `/day/{date}` are the same shape to
FastAPI, and whichever is declared first wins — so this router is registered
ahead of the day's in `app.main`, and `debt` is a word rather than a date that
fails to parse.

**Ни одного пути, которым потолок поднимается сам.** The proposal endpoint reads
and returns; the ceiling moves on `POST /day/rules/activations` and nowhere else.
That is the decision of 2026-08-30 expressed as a shape of the API rather than
as a rule somebody has to remember.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.daytime import now_utc, today_local
from app.crud import day_profile as profile_crud
from app.crud import summary as summary_crud
from app.crud.day_profile import deadline_signals
from app.day.profiles import propose_profile
from app.models.day_profile import DayRuleActivation, DayRuleProfile
from app.schemas.day_profile import (
    ActivationIn,
    ActivationResponse,
    DayRuleProfileIn,
    DayRuleProfileResponse,
    DebtLedgerResponse,
    DebtResponse,
    ProfileProposalResponse,
)

# Окно, за которое считаются длинные дни для предложения: последние семь,
# потому что предложение — про неделю, а не про вчера.
PROPOSAL_WINDOW_DAYS = 7

router = APIRouter(prefix="/day", tags=["day"])

# --- потолок работы дышит (#179) -------------------------------------------
#
# Опасность названа прямо: потолок, который сам растёт под дедлайн, отменяет
# правило. Поэтому здесь нет ни одного пути, которым потолок поднимается без
# подтверждения человеком, и каждый поднятый час создаёт долг.


def _profile_dto(profile: DayRuleProfile) -> DayRuleProfileResponse:
    return DayRuleProfileResponse(
        id=profile.id,
        code=profile.code,
        title=profile.title,
        work_cap_min=profile.work_cap_min,
        work_hard_cap_min=profile.work_hard_cap_min,
        required_anchors=[str(kind) for kind in profile.required_anchors],
        is_default=profile.is_default,
    )


def _activation_dto(
    row: DayRuleActivation, codes: dict[int, str], today: date
) -> ActivationResponse:
    return ActivationResponse(
        id=row.id,
        profile_code=codes[row.profile_id],
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        reason=row.reason,
        confirmed_at=row.confirmed_at,
        declined_at=row.declined_at,
        source_signal_id=row.source_signal_id,
        is_in_force=(
            row.confirmed_at is not None and row.valid_from <= today <= row.valid_to
        ),
    )


@router.get("/rules/profiles", response_model=list[DayRuleProfileResponse])
async def get_profiles(
    db: AsyncSession = Depends(get_db),
) -> list[DayRuleProfileResponse]:
    """Именованные наборы потолков: базовый первым."""
    return [_profile_dto(row) for row in await profile_crud.list_profiles(db)]


@router.post("/rules/profiles", response_model=DayRuleProfileResponse)
async def post_profile(
    body: DayRuleProfileIn, db: AsyncSession = Depends(get_db)
) -> DayRuleProfileResponse:
    """
    Завести или поправить набор потолков — по коду, а не по id.

    Правка, а не версия: профиль это именованный набор чисел, а какие даты им
    судились, помнит `day_rule_activation`. Прошлые вердикты правка не трогает —
    они пересчитываются только при закрытии дня, и каждый день считается
    профилем своей даты.
    """
    existing = await profile_crud.get_profile_by_code(db, body.code)
    if existing is None:
        existing = DayRuleProfile(code=body.code, title=body.title)
        db.add(existing)
    existing.title = body.title
    existing.work_cap_min = body.work_cap_min
    existing.work_hard_cap_min = body.work_hard_cap_min
    existing.required_anchors = list(body.required_anchors)
    await db.flush()
    await db.commit()
    await db.refresh(existing)
    return _profile_dto(existing)


def _is_raised(in_force: profile_crud.ProfileInForce | None) -> bool:
    """Whether a raise is already on: a proposal on top of one is how twelve becomes fourteen."""
    return in_force is not None and in_force.valid_to is not None


@router.get("/rules/proposal", response_model=ProfileProposalResponse | None)
async def get_proposal(
    db: AsyncSession = Depends(get_db),
) -> ProfileProposalResponse | None:
    """
    Текущее предложение поднять потолок — с причиной или пусто.

    Пусто — обычный ответ. Признак «дедлайн близко» приходит из рабочего
    ClickUp (`#103`); пока источника нет, список сигналов пуст и предложения не
    бывает, и это правильное поведение, а не деградация.

    Предложение ничего не меняет. Потолок двигает только подтверждение
    (`POST /day/rules/activations`) — решение человека 2026-08-30.
    """
    today = today_local()
    long_days = await summary_crud.days_over_cap(
        db, today - timedelta(days=PROPOSAL_WINDOW_DAYS), today
    )
    proposal = propose_profile(
        signals=await deadline_signals(db),
        long_days=long_days,
        today=today,
        declined_signal_ids=await profile_crud.declined_signal_ids(db),
        active=_is_raised(await profile_crud.profile_for(db, today)),
    )
    if proposal is None:
        return None
    profile = await profile_crud.get_profile_by_code(db, proposal.profile_code)
    if profile is None:  # pragma: no cover - seeded by the migration
        return None
    return ProfileProposalResponse(
        profile_code=proposal.profile_code,
        title=profile.title,
        work_cap_min=profile.work_cap_min,
        valid_from=proposal.valid_from,
        valid_to=proposal.valid_to,
        reason=proposal.reason,
        source_signal_id=proposal.source_signal_id,
    )


@router.get("/rules/activations", response_model=list[ActivationResponse])
async def get_activations(
    db: AsyncSession = Depends(get_db),
) -> list[ActivationResponse]:
    """Какой профиль когда действовал и почему; отказы тоже видны."""
    rows = await profile_crud.activations(db)
    codes = {row.id: row.code for row in await profile_crud.list_profiles(db)}
    today = today_local()
    return [_activation_dto(row, codes, today) for row in rows]


@router.post(
    "/rules/activations",
    response_model=ActivationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_activation(
    body: ActivationIn, db: AsyncSession = Depends(get_db)
) -> ActivationResponse:
    """
    Подтвердить поднятый потолок. Это единственный путь, которым он двигается.

    Срок и причина обязательны: активация без срока — потолок, который некому
    выключить, а без причины — подъём, который через месяц нечем объяснить.
    """
    profile = await profile_crud.get_profile_by_code(db, body.profile_code)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unknown profile code: {body.profile_code}",
        )
    if body.valid_to < body.valid_from:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="valid_to раньше valid_from",
        )
    row = await profile_crud.create_activation(
        db,
        profile_id=profile.id,
        valid_from=body.valid_from,
        valid_to=body.valid_to,
        reason=body.reason,
        source_signal_id=body.source_signal_id,
        confirmed_at=now_utc(),
    )
    await summary_crud.recompute_history(db)
    await db.commit()
    return _activation_dto(row, {profile.id: profile.code}, today_local())


@router.delete("/rules/activations/{activation_id}", response_model=ActivationResponse)
async def delete_activation(
    activation_id: int, db: AsyncSession = Depends(get_db)
) -> ActivationResponse:
    """
    Отказаться от подъёма — досрочно или в ответ на предложение.

    Строка остаётся и теряет подтверждение, а не удаляется: отказ — это тот
    факт, из-за которого то же предложение не приходит завтра снова.
    """
    row = await profile_crud.get_activation(db, activation_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="day rule activation"
        )
    await profile_crud.decline_activation(db, row, now_utc())
    await summary_crud.recompute_history(db)
    await db.commit()
    codes = {item.id: item.code for item in await profile_crud.list_profiles(db)}
    return _activation_dto(row, codes, today_local())


@router.get("/debt", response_model=DebtLedgerResponse)
async def get_debt(db: AsyncSession = Depends(get_db)) -> DebtLedgerResponse:
    """
    Долг за переработку: сколько минут не вернулось и с каких дней.

    Долг, висящий дольше недели, — проваленное правило, а не справка; `days_open`
    даёт экрану число, по которому он это показывает.
    """
    today = today_local()
    rows = await profile_crud.list_debts(db)
    return DebtLedgerResponse(
        open_minutes=sum(row.minutes_over for row in rows if row.repaid_on is None),
        debts=[
            DebtResponse(
                incurred_on=row.incurred_on,
                minutes_over=row.minutes_over,
                repaid_on=row.repaid_on,
                repaid_by_day=row.repaid_by_day,
                is_open=row.repaid_on is None,
                days_open=(
                    (today - row.incurred_on).days
                    if row.repaid_on is None
                    else (row.repaid_on - row.incurred_on).days
                ),
            )
            for row in rows
        ],
    )
