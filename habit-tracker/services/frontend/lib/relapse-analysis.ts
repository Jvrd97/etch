// [review:need-review] PHASE-01/207
// summary: pure analysis of an avoid category's relapse days — counts for the last week and month, the average gap, the weekday split, the trend against the month before, and the day or week buckets the history chart draws

/**
 * Анализ дней срыва одной avoid-категории.
 *
 * Модуль не решает, что такое срыв: дни приходят готовыми из
 * `GET /categories/{id}/relapses`, правило живёт на сервере. Здесь только
 * арифметика по датам `YYYY-MM-DD`. Даты переводятся в номер дня UTC, а не в
 * локальную полночь: между двумя датами ровно столько суток, сколько написано,
 * и переход на летнее время не съедает час из разницы.
 */

import { plural } from './challenges';

const MS_PER_DAY = 86_400_000;
const DAYS_PER_WEEK = 7;

/** The trailing windows of the summary, today included. */
export const WEEK_DAYS = 7;
export const MONTH_DAYS = 30;

/** Up to this many days the chart draws one bar per day, past it one per week. */
export const DAILY_BUCKET_LIMIT = 90;

export type RelapsePeriod = '30d' | '90d' | '365d' | 'all';

export const RELAPSE_PERIODS: readonly RelapsePeriod[] = ['30d', '90d', '365d', 'all'];

export const RELAPSE_PERIOD_LABELS: Record<RelapsePeriod, string> = {
  '30d': '30 дней',
  '90d': '90 дней',
  '365d': 'Год',
  all: 'Всё время',
};

/** The period as the tail of a sentence: «график срывов за год». */
export const RELAPSE_PERIOD_PHRASES: Record<RelapsePeriod, string> = {
  '30d': 'за 30 дней',
  '90d': 'за 90 дней',
  '365d': 'за год',
  all: 'за всё время',
};

const PERIOD_DAYS: Record<Exclude<RelapsePeriod, 'all'>, number> = {
  '30d': 30,
  '90d': 90,
  '365d': 365,
};

/** Monday first, the way a Russian calendar reads a week. */
export const WEEKDAY_LABELS: readonly string[] = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];

const MONTH_LABELS: readonly string[] = [
  'янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек',
];

/** Days since 1970-01-01 of a `YYYY-MM-DD` string. */
function dayNumber(iso: string): number {
  const [year, month, day] = iso.split('-').map(Number);
  return Math.round(Date.UTC(year, month - 1, day) / MS_PER_DAY);
}

function isoOf(day: number): string {
  return new Date(day * MS_PER_DAY).toISOString().slice(0, 10);
}

/** 0 for Monday … 6 for Sunday. */
function weekdayIndex(day: number): number {
  const sundayFirst = new Date(day * MS_PER_DAY).getUTCDay();
  return (sundayFirst + DAYS_PER_WEEK - 1) % DAYS_PER_WEEK;
}

/** «25 окт 2026» — the same on every machine, unlike `Intl` output. */
export function formatRelapseDay(iso: string): string {
  const [year, month, day] = iso.split('-').map(Number);
  return `${day} ${MONTH_LABELS[month - 1]} ${year}`;
}

/** «Вт» — the weekday of a `YYYY-MM-DD` date. */
export function formatWeekday(iso: string): string {
  return WEEKDAY_LABELS[weekdayIndex(dayNumber(iso))];
}

/** «1 день», «3 дня», «12 дней». */
export function formatDayCount(days: number): string {
  return `${days} ${plural(days, 'день', 'дня', 'дней')}`;
}

/** An average gap: whole days as a count, a fraction with a comma and «дня». */
export function formatGap(days: number): string {
  if (Number.isInteger(days)) return formatDayCount(days);
  return `${days.toFixed(1).replace('.', ',')} дня`;
}

/** «25.10» — a short axis label. */
export function formatShortDay(iso: string): string {
  const [, month, day] = iso.split('-');
  return `${day}.${month}`;
}

/**
 * How this month compares with the one before it.
 *
 * `not-enough-data` until the history reaches back over both months: a month
 * that was not tracked is not a clean month, and calling it one would make every
 * new category look worse than «месяц назад».
 */
export type RelapseTrend =
  | { kind: 'not-enough-data' }
  | { kind: 'fewer' | 'more' | 'same'; current: number; previous: number };

export interface RelapseSummary {
  /** Relapse days in the last `WEEK_DAYS` days, today included. */
  lastWeek: number;
  /** Relapse days in the last `MONTH_DAYS` days, today included. */
  lastMonth: number;
  /** Mean number of days between two consecutive relapse days, or null below two. */
  averageGapDays: number | null;
  /** Relapse days per weekday over the whole history, Monday first. */
  weekdays: number[];
  trend: RelapseTrend;
}

function uniqueDays(relapseDates: readonly string[]): number[] {
  return [...new Set(relapseDates.map(dayNumber))].sort((a, b) => a - b);
}

function countBetween(days: readonly number[], from: number, to: number): number {
  return days.filter((day) => day >= from && day <= to).length;
}

export function summarizeRelapses(
  relapseDates: readonly string[],
  trackedSince: string | null,
  today: string
): RelapseSummary {
  const days = uniqueDays(relapseDates);
  const todayNumber = dayNumber(today);

  const gaps = days.slice(1).map((day, index) => day - days[index]);
  const averageGapDays =
    gaps.length === 0 ? null : gaps.reduce((sum, gap) => sum + gap, 0) / gaps.length;

  const weekdays = Array.from({ length: DAYS_PER_WEEK }, () => 0);
  for (const day of days) weekdays[weekdayIndex(day)] += 1;

  const monthStart = todayNumber - MONTH_DAYS + 1;
  const previousStart = monthStart - MONTH_DAYS;
  const lastMonth = countBetween(days, monthStart, todayNumber);

  let trend: RelapseTrend = { kind: 'not-enough-data' };
  if (trackedSince !== null && dayNumber(trackedSince) <= previousStart) {
    const previous = countBetween(days, previousStart, monthStart - 1);
    const kind = lastMonth < previous ? 'fewer' : lastMonth > previous ? 'more' : 'same';
    trend = { kind, current: lastMonth, previous };
  }

  return {
    lastWeek: countBetween(days, todayNumber - WEEK_DAYS + 1, todayNumber),
    lastMonth,
    averageGapDays,
    weekdays,
    trend,
  };
}

/** One bar of the history chart: a day or a week and how many relapse days it held. */
export interface RelapseBucket {
  /** First day of the bucket, `YYYY-MM-DD`. */
  start: string;
  /** Last day of the bucket, `YYYY-MM-DD`; equal to `start` for a day bucket. */
  end: string;
  relapseDays: number;
}

export interface RelapseTimeline {
  granularity: 'day' | 'week';
  buckets: RelapseBucket[];
}

/**
 * The bars of the history chart for `period`, oldest first, ending today.
 *
 * `all` starts at the first tracked day (or the first relapse, if it is
 * earlier). Weeks start on Monday, so a bar is always the same calendar week
 * whichever period is chosen; the first one may begin before the period does
 * and the last one may end after today, but only days of the period are counted.
 */
export function relapseTimeline(
  relapseDates: readonly string[],
  trackedSince: string | null,
  today: string,
  period: RelapsePeriod
): RelapseTimeline {
  const days = uniqueDays(relapseDates);
  const end = dayNumber(today);
  let start: number;
  if (period === 'all') {
    const candidates = [end, ...(trackedSince === null ? [] : [dayNumber(trackedSince)])];
    if (days.length > 0) candidates.push(days[0]);
    start = Math.min(...candidates);
  } else {
    start = end - PERIOD_DAYS[period] + 1;
  }

  if (end - start + 1 <= DAILY_BUCKET_LIMIT) {
    const buckets: RelapseBucket[] = [];
    for (let day = start; day <= end; day += 1) {
      buckets.push({ start: isoOf(day), end: isoOf(day), relapseDays: countBetween(days, day, day) });
    }
    return { granularity: 'day', buckets };
  }

  const buckets: RelapseBucket[] = [];
  for (let week = start - weekdayIndex(start); week <= end; week += DAYS_PER_WEEK) {
    const weekEnd = week + DAYS_PER_WEEK - 1;
    buckets.push({
      start: isoOf(week),
      end: isoOf(weekEnd),
      relapseDays: countBetween(days, Math.max(week, start), Math.min(weekEnd, end)),
    });
  }
  return { granularity: 'week', buckets };
}
