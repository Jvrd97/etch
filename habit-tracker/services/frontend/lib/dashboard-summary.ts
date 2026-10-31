// [review:need-review] #302
// summary: pure wording and arithmetic of the dashboard summary - short Russian dates read off the string, minutes as hours, units of the Health catalog, the sign and the good direction of a distance from the personal norm, tallies of day dots, workout bar heights and the Russian error text

import { APIError, type DashboardDayMark, type DashboardPeriod, type DashboardWorkoutWeek } from '@/lib/api';

export const DASHBOARD_PERIODS: ReadonlyArray<{ id: DashboardPeriod; label: string }> = [
  { id: 'week', label: 'Неделя' },
  { id: 'month', label: 'Месяц' },
];

export const DEFAULT_DASHBOARD_PERIOD: DashboardPeriod = 'week';

/** Days of data below which the server gives no health score. */
export const HEALTH_SCORE_MIN_DAYS = 3;

const MINUTES_PER_HOUR = 60;
export const MINUS = '\u2212';
const NO_VALUE = '—';
const THIN_NBSP = ' ';

const MONTHS_SHORT = [
  'янв',
  'фев',
  'мар',
  'апр',
  'мая',
  'июн',
  'июл',
  'авг',
  'сен',
  'окт',
  'ноя',
  'дек',
] as const;

const ISO_DAY = /^(\d{4})-(\d{2})-(\d{2})/;
const ISO_MOMENT = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})/;

/** `2026-10-28` as «28 окт». Read off the string: a date has no time zone to shift it. */
export function formatDayShort(iso: string): string {
  const match = ISO_DAY.exec(iso);
  if (match === null) return iso;
  const month = MONTHS_SHORT[Number(match[2]) - 1];
  if (month === undefined) return iso;
  return `${Number(match[3])} ${month}`;
}

export function formatRange(from: string, to: string): string {
  return `${formatDayShort(from)} — ${formatDayShort(to)}`;
}

/**
 * «31 окт, 09:00» out of an ISO moment, as the server wrote it. The offset is
 * dropped on purpose: the insight was made in the server's day, and converting
 * it to the browser's zone could move it to another date.
 */
export function formatGeneratedAt(iso: string): string {
  const match = ISO_MOMENT.exec(iso);
  if (match === null) return '';
  return `${formatDayShort(match[1])}, ${match[2]}:${match[3]}`;
}

export function formatMinutes(minutes: number): string {
  const total = Math.max(0, Math.round(minutes));
  const hours = Math.floor(total / MINUTES_PER_HOUR);
  const rest = total % MINUTES_PER_HOUR;
  if (hours === 0) return `${rest} мин`;
  return rest === 0 ? `${hours} ч` : `${hours} ч ${rest} мин`;
}

function formatNumber(value: number): string {
  const rounded = Number.isInteger(value) ? value : Math.round(value * 10) / 10;
  const [whole, fraction] = String(Math.abs(rounded)).split('.');
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, THIN_NBSP);
  const sign = rounded < 0 ? MINUS : '';
  return fraction === undefined ? `${sign}${grouped}` : `${sign}${grouped},${fraction}`;
}

/** Units of the Health catalog that read better in Russian; the rest are shown as the server named them. */
const UNIT_SUFFIX: Readonly<Record<string, string>> = {
  'count/min': 'уд/мин',
  ms: 'мс',
  kcal: 'ккал',
  km: 'км',
  m: 'м',
  '%': '%',
};
const UNITLESS = new Set(['count']);

export function formatMetricValue(value: number | null, unit: string): string {
  if (value === null) return NO_VALUE;
  if (unit === 'min') return formatMinutes(value);
  if (UNITLESS.has(unit)) return formatNumber(value);
  const suffix = UNIT_SUFFIX[unit] ?? unit;
  return suffix === '%' ? `${formatNumber(value)}%` : `${formatNumber(value)} ${suffix}`;
}

/** The distance from the personal norm: signed, in the metric's own unit. */
export function formatDelta(delta: number | null, unit: string): string {
  if (delta === null) return 'нормы пока нет';
  if (delta === 0) return 'на уровне нормы';
  const sign = delta > 0 ? '+' : MINUS;
  const magnitude = Math.abs(delta);
  return `${sign}${unit === 'min' ? formatMinutes(magnitude) : formatMetricValue(magnitude, unit)}`;
}

export type DeltaTone = 'good' | 'bad' | 'neutral';

/**
 * Which way is better for the key metrics, by their full Health catalog name.
 * Only a fallback for an answer without `higher_is_better`: the server knows the
 * direction, and a guess from a part of the name is how a new metric gets the
 * wrong colour.
 */
const HIGHER_IS_BETTER: Readonly<Record<string, boolean>> = {
  HKQuantityTypeIdentifierRestingHeartRate: false,
  HKQuantityTypeIdentifierHeartRateVariabilitySDNN: true,
  HKCategoryTypeIdentifierSleepAnalysis: true,
  HKQuantityTypeIdentifierStepCount: true,
  HKQuantityTypeIdentifierActiveEnergyBurned: true,
};

/** `higherIsBetter` from the server wins; a metric the table does not list is described, not judged. */
export function deltaTone(
  identifier: string,
  delta: number | null,
  higherIsBetter?: boolean
): DeltaTone {
  if (delta === null || delta === 0) return 'neutral';
  const better = higherIsBetter ?? HIGHER_IS_BETTER[identifier];
  if (better === undefined) return 'neutral';
  return delta > 0 === better ? 'good' : 'bad';
}

export const TONE_WORDS: Readonly<Record<DeltaTone, string | null>> = {
  good: 'лучше нормы',
  bad: 'хуже нормы',
  neutral: null,
};

const HEALTH_LABELS: Readonly<Record<string, string>> = {
  good: 'Хорошо',
  fair: 'Средне',
  poor: 'Ниже нормы',
};

export function healthLabelText(label: string | null): string | null {
  return label === null ? null : (HEALTH_LABELS[label] ?? null);
}

export interface DayTally {
  done: number;
  missed: number;
  unknown: number;
}

export function streakDaysTally(days: ReadonlyArray<DashboardDayMark>): DayTally {
  const tally: DayTally = { done: 0, missed: 0, unknown: 0 };
  for (const day of days) {
    if (day === true) tally.done += 1;
    else if (day === false) tally.missed += 1;
    else tally.unknown += 1;
  }
  return tally;
}

/** Bar heights in 0..1, scaled to the busiest week; a window with no workout stays flat. */
export function workoutBarFractions(weeks: ReadonlyArray<DashboardWorkoutWeek>): number[] {
  const busiest = Math.max(0, ...weeks.map((week) => week.count));
  return weeks.map((week) => (busiest === 0 ? 0 : week.count / busiest));
}

const SERVER_ERROR_FROM = 500;

/** The sentence under a failed summary: Russian, and honest about whose fault it is. */
export function dashboardErrorMessage(error: unknown): string {
  if (error instanceof APIError && error.status >= SERVER_ERROR_FROM) {
    return 'Сервер не смог собрать сводку. Попробуйте ещё раз через минуту.';
  }
  if (error instanceof APIError) {
    return 'Не удалось получить сводку. Обновите страницу или войдите заново.';
  }
  return 'Не удалось загрузить сводку: проверьте соединение и попробуйте ещё раз.';
}
