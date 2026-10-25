# [review:need-review] PHASE-01/27-streak-mode-endpoint, PHASE-01/207
# summary: StreakResponse DTO (current/best streak, last relapse date, streak mode) and RelapseHistoryResponse — the same numbers plus every relapse day and the first tracked day
from datetime import date

from pydantic import BaseModel

from app.schemas.category import CategoryStreakMode


class StreakResponse(BaseModel):
    """Streak numbers of a category, computed over its whole history."""

    category_id: int
    streak_mode: CategoryStreakMode
    current_streak: int
    best_streak: int
    last_relapse_date: date | None


class RelapseHistoryResponse(StreakResponse):
    """
    The streak with the days it broke on, for the category page.

    A separate read rather than a field of `StreakResponse`: Today and the
    dashboard read the streaks of every avoid category at once and need only
    the numbers, while the history is a whole timeline per category.
    """

    # The first tracked day, so the page knows how far back «a month ago» is real.
    tracked_since: date | None
    # Every day that held a relapse, ascending.
    relapse_dates: list[date]
