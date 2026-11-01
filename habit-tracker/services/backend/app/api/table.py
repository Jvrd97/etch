# [review:need-review] PHASE-01/04-backend-table-endpoint, 309
# summary: GET /api/v1/table — aggregated per-day table view over a date range; optional repeated `category_id` narrows it to those categories (#309)
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.crud import table as table_crud
from app.schemas import TableResponse

router = APIRouter(prefix="/table", tags=["table"])

# Upper bound for the requested range (leap year), DoS guard:
# each day materializes a TableDay object in memory.
MAX_RANGE_DAYS = 366


@router.get("", response_model=TableResponse)
async def get_table(
    date_from: date = Query(
        ..., description="Start of the range, inclusive (YYYY-MM-DD)"
    ),
    date_to: date = Query(..., description="End of the range, inclusive (YYYY-MM-DD)"),
    category_id: list[int] | None = Query(
        None,
        description=(
            "Only these categories (repeatable): their cells and their metadata. "
            "Absent — every active category."
        ),
    ),
    db: AsyncSession = Depends(get_db),
) -> TableResponse:
    """
    Табличное представление: агрегированные значения полей по дням.

    Для каждого дня диапазона возвращается список ячеек
    `{category_id, field_id, aggregated_value, entry_count}`.
    Агрегация: number — сумма за день, boolean — any,
    остальные типы — последнее значение по created_at.

    `category_id` (можно несколько) сужает ячейки и метаданные до этих
    категорий: экран категории строит график по своему году, а не по всем.
    """
    if date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="date_from must be <= date_to",
        )
    range_days = (date_to - date_from).days + 1
    if range_days > MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"date range is too long: {range_days} days requested, "
                f"maximum is {MAX_RANGE_DAYS} days"
            ),
        )
    return await table_crud.get_table(
        db, date_from=date_from, date_to=date_to, category_ids=category_id
    )
