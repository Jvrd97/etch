// [review:need-review] PHASE-03/221
// summary: vocabulary of the week review screen — minutes and deltas as words, the note under an unfinished week, health values by unit, the empty test mirrored from the server, narrative errors by HTTP status, and the links between weeks

import { WEEKDAY_SHORT } from '@/lib/life';
import type { WeekReview, WeekReviewHealth, WeekReviewWindow } from '@/lib/api';

const MINUTES_PER_HOUR = 60;
const MINUS = '−';

/** Prefix of every week-review route; the mobile shell adds `/m` in front. */
export const WEEK_REVIEW_PATH = '/week/review';

export const NO_DATA = 'Нет данных';
export const NO_CHANGE = 'без изменений';
export const NOT_CLOSED = 'не закрыт';

/** Said in place of the screen's numbers when the week holds nothing at all. */
export const EMPTY_WEEK_TEXT = 'За эту неделю данных пока нет.';

export const METRIC_MISSING_TEXT = 'Метрика не подключена';

/** `75` minutes as «1 ч 15 мин»; a bare hour has no «0 мин» tail. */
export function formatMinutes(minutes: number): string {
  const total = Math.max(0, Math.round(minutes));
  const hours = Math.floor(total / MINUTES_PER_HOUR);
  const rest = total % MINUTES_PER_HOUR;
  if (hours === 0) return `${rest} мин`;
  if (rest === 0) return `${hours} ч`;
  return `${hours} ч ${String(rest).padStart(2, '0')} мин`;
}

function signed(value: number, text: (abs: number) => string): string {
  if (value === 0) return NO_CHANGE;
  return `${value > 0 ? '+' : MINUS}${text(Math.abs(value))}`;
}

/** Change in minutes against the previous week: «+1 ч 20 мин», «−45 мин». */
export function deltaMinutes(delta: number | null): string | null {
  return delta === null ? null : signed(delta, formatMinutes);
}

/** Change in a count: «+2», «−1». */
export function deltaCount(delta: number): string {
  return signed(delta, String);
}

/** Change of a share in percentage points: «+29 п.п.». */
export function deltaPoints(delta: number | null): string | null {
  return delta === null ? null : signed(delta, (abs) => `${abs} п.п.`);
}

/** Whether a change is for the better, the worse, or neither — for colour, never alone. */
export type Trend = 'up' | 'down' | 'flat';

export function trendOf(delta: number | null): Trend {
  if (delta === null || delta === 0) return 'flat';
  return delta > 0 ? 'up' : 'down';
}

/**
 * The line under the title of a week that has not ended.
 *
 * Null for a finished week: nothing needs saying. For a running one it names
 * both counts, because the comparison covers the same number of days of the
 * previous week and a reader who sees «−3 задачи» must know the week is short.
 */
export function partialNote(window: WeekReviewWindow): string | null {
  if (window.is_complete) return null;
  if (window.counted_days === 0) return 'Неделя ещё не началась.';
  return `Неделя не закончилась: учтено ${window.counted_days} из 7 дней. Сравнение — с первыми ${window.compared_days} днями прошлой недели.`;
}

/** `YYYY-MM-DD` as «24.08», parsed by hand so no timezone can move the day. */
export function shortDate(iso: string): string {
  const [, month, day] = iso.split('-');
  return `${day}.${month}`;
}

export function periodText(window: WeekReviewWindow): string {
  return `${shortDate(window.starts_on)} — ${shortDate(window.ends_on)}`;
}

export function weekdayShort(weekday: number): string {
  return WEEKDAY_SHORT[weekday] ?? '';
}

export function weekHref(iso: string): string {
  return `${WEEK_REVIEW_PATH}/${iso}`;
}

/** A health value in the unit the catalog gave it: minutes as hours, counts as integers. */
export function formatHealthValue(unit: string | null, value: number): string {
  if (unit === 'min') return formatMinutes(value);
  if (unit === 'count') return Math.round(value).toLocaleString('ru-RU');
  return `${value}${unit ? ` ${unit}` : ''}`;
}

/** The change of a daily average, formatted in the same unit; null when there is nothing to compare. */
export function formatHealthDelta(metric: WeekReviewHealth): string | null {
  const delta = metric.delta_avg_per_day;
  if (delta === null) return null;
  return signed(delta, (abs) => formatHealthValue(metric.unit, abs));
}

/** The server's emptiness test, repeated so the button is off exactly when the server would refuse. */
export function isEmptyWeek(review: WeekReview): boolean {
  return (
    review.totals.closed_days === 0 &&
    review.totals.tasks_total === 0 &&
    review.totals.role_minutes === 0 &&
    review.categories.length === 0 &&
    review.health.every((metric) => metric.days_with_data === 0)
  );
}

export const NARRATIVE_ERRORS: Record<number, string> = {
  422: 'В этой неделе нет данных для итога.',
  502: 'Модель не ответила. Повторите позже.',
  503: 'Итог от ИИ выключен: не настроен бэкенд модели.',
};

export const NARRATIVE_ERROR_FALLBACK = 'Не удалось написать итог недели.';

/** The HTTP status is read off the error by shape, so this module imports no value from the API client. */
export function narrativeErrorText(error: unknown): string {
  if (typeof error === 'object' && error !== null && 'status' in error) {
    const status = (error as { status: unknown }).status;
    if (typeof status === 'number' && status in NARRATIVE_ERRORS) {
      return NARRATIVE_ERRORS[status];
    }
  }
  return NARRATIVE_ERROR_FALLBACK;
}
