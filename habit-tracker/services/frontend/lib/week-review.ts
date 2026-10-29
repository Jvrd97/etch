// [review:need-review] PHASE-03/221, PHASE-03/239, PHASE-03/255
// summary: vocabulary of the week review screen — the note on role shares of a running week (off once today is counted), minutes and deltas as words, the note under an unfinished week, health values by unit, the empty test mirrored from the server, narrative errors by HTTP status, and the links between weeks

import { WEEKDAY_SHORT } from '@/lib/life';
import { toMobilePath } from '@/lib/view-mode';
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

/** Nothing is counted: the week has not begun, or its first day is still open. */
export const NO_COUNTED_DAYS_TEXT =
  'Пока нет ни одного учтённого дня: неделя не началась или её первый день ещё не закрыт.';

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
  if (window.counted_days === 0) return NO_COUNTED_DAYS_TEXT;
  const today = window.today_counted ? '' : ', сегодняшний день войдёт после закрытия';
  return `Неделя не закончилась: учтено ${window.counted_days} из 7 дней — закрытые и прошедшие${today}. Сравнение — с первыми ${window.compared_days} днями прошлой недели.`;
}

/**
 * Said under the role shares of a week that has not ended.
 *
 * The review leaves today out until its day is closed; the retro page of the same
 * week counts today's minutes at once, so the two shares differ by a day. Once the
 * server says today is counted (`today_counted`), both pages cover the same days and
 * the line would be false, so it goes.
 */
export const ROLES_RUNNING_WEEK_NOTE =
  'Доли считаются по учтённым дням: минуты сегодняшнего дня войдут после его закрытия, а на странице «Ретро недели» они уже есть, поэтому доли там могут отличаться.';

export function rolesNote(window: WeekReviewWindow): string | null {
  return window.is_complete || window.today_counted ? null : ROLES_RUNNING_WEEK_NOTE;
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

/**
 * A desktop address in the shell the screen is drawn in.
 *
 * `compact` is the mobile shell's flag; the mapping itself is `toMobilePath`'s,
 * so the link of a `/m` page cannot drop the reader out of the shell and the
 * pair of routes is described in exactly one place.
 */
function inShell(desktopHref: string, compact: boolean): string {
  return compact ? (toMobilePath(desktopHref) ?? desktopHref) : desktopHref;
}

/** The review of a named week, in the reader's shell. */
export function weekHref(iso: string, compact = false): string {
  return inShell(`${WEEK_REVIEW_PATH}/${iso}`, compact);
}

/** The retro page of a named week, in the reader's shell. */
export function retroHref(iso: string, compact = false): string {
  return inShell(`/week/${iso}`, compact);
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
    review.habit_streaks.length === 0 &&
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
