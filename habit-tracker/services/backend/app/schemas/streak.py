# [review:need-review] PHASE-01/27-streak-mode-endpoint, PHASE-01/207, PHASE-03/294
# summary: PHASE-03/294 — RelapseRecordRequest, the optional day a Happened is recorded on
# summary: PHASE-03/294 — RelapseRecordRequest, the optional day a Happened is recorded on
# summary: StreakResponse DTO (current/best streak, last relapse date, streak mode); RelapseHistoryResponse — the same numbers plus every relapse day, the first tracked day and the server's today; RelapseRecordedResponse — the entry a Happened tap landed on and whether that tap wrote it
from datetime import date

from pydantic import BaseModel

from app.schemas.category import CategoryStreakMode
from app.schemas.entry import EntryResponse


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
    # «Сегодня» by the day rule in force (the day may end at 04:00, not at
    # midnight), so the page counts its week and month from the same day the
    # streak was counted to, not from the browser's calendar.
    today: date


class RelapseRecordRequest(BaseModel):
    """
    Optional body of a Happened: the day the relapse happened on.

    No body, or no `entry_date`, is today by the day rule in force. A day after
    that today is refused: a relapse cannot be recorded ahead of time.
    """

    entry_date: date | None = None


class RelapseRecordedResponse(EntryResponse):
    """
    The entry a Happened tap landed on.

    `created` is true when this request — or an earlier attempt under the same
    Idempotency-Key — wrote the entry, so the tap may take it back. It is false
    when the tap landed on a relapse already recorded within the repeat window:
    that entry is somebody else's (a quick mark, another tab), and undoing this
    tap must not delete it.
    """

    created: bool
