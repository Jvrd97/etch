// [review:need-review] #78, PHASE-03/264
// summary: pure maths of the dashboard Trends block - period windows over one GET /table range, top-4 category selection, daily average, delta to the previous period, sparkline points and geometry, readable series color
// summary: #264 — the period windows are counted back from the moment passed in with `toISODate`, so a screen that passes the server's day is not moved by a suite's fixed `todayISO` mock

import type { Category, TableDay } from './api';
import { SERIES_COLORS, parseCellValue, type ChartPeriod } from './chart-data';
import { fromISODate, toISODate } from './date';
import { formatValue } from './format-value';
import { firstNumberField } from './today-categories';

export const TREND_PERIODS = [7, 30, 90] as const;
export type TrendPeriod = (typeof TREND_PERIODS)[number];

/** Desktop shows this period only, and the category chart opens on it by default. */
export const DEFAULT_TREND_PERIOD: TrendPeriod = 30;

/** Rows in the block; the mockup draws four. */
const MAX_TREND_CATEGORIES = 4;
const AVERAGE_DECIMALS = 1;
const PERCENT = 100;

/**
 * Card background the sparkline is drawn on; keep in sync with `--color-card`
 * in `app/globals.css`.
 */
const CARD_SURFACE = '#1a1a1a';
/** WCAG 2.2 SC 1.4.11: a graphical object needs 3:1 against its neighbour. */
const MIN_GRAPHIC_CONTRAST = 3;
const HEX_COLOR = /^#([0-9a-f]{6})$/i;
const SRGB_LINEAR_CUTOFF = 0.03928;
const LUMINANCE_WEIGHTS = [0.2126, 0.7152, 0.0722] as const;
const CONTRAST_FLARE = 0.05;

/** A `?period=` value from a trend link, or null when it is not one of the offered periods. */
export function parseTrendPeriod(value: string | null | undefined): TrendPeriod | null {
  return TREND_PERIODS.find((period) => String(period) === value) ?? null;
}

/** The category chart period that covers exactly the same days as `period`. */
export function chartPeriodFor(period: TrendPeriod): ChartPeriod {
  return `${period}d`;
}

export interface TrendPoint {
  date: string;
  /** Daily sum of the field; null on a day without a numeric value, which is not zero. */
  value: number | null;
}

export interface DashboardTrend {
  categoryId: number;
  categoryName: string;
  icon: string | null;
  unit: string | null;
  color: string;
  /** Mean of the daily sums over the days that have a value; a listed row always has one. */
  average: number;
  /** Percent change of `average` against the previous period; null when it cannot be told. */
  deltaPercent: number | null;
  sparkline: TrendPoint[];
}

/** `count` local calendar dates ending today, oldest first. */
function datesEndingToday(count: number, now: Date): string[] {
  // `toISODate(now)`, not `todayISO(now)`: suites replace `todayISO` with a fixed day that ignores `now`.
  const end = fromISODate(toISODate(now));
  return Array.from({ length: count }, (_, index) => {
    const date = new Date(end);
    date.setDate(end.getDate() - (count - 1 - index));
    return toISODate(date);
  });
}

/**
 * One `GET /table` range that covers the period and the one before it, so the
 * delta costs no second request. The longest period is 180 days, well inside
 * the 366 the endpoint accepts.
 */
export function trendDateRange(
  period: TrendPeriod,
  now: Date = new Date()
): { dateFrom: string; dateTo: string } {
  const dates = datesEndingToday(period * 2, now);
  return { dateFrom: dates[0], dateTo: dates[dates.length - 1] };
}

function dailyValue(day: TableDay, categoryId: number, fieldId: number): number | null {
  const cell = day.cells.find((item) => item.category_id === categoryId && item.field_id === fieldId);
  return parseCellValue('number', cell?.aggregated_value ?? null);
}

/**
 * Mean of the daily sums over the days that have a numeric value.
 *
 * A day with no entry is not a zero: someone who logs pushups on three days of
 * thirty still did 40 a day on those three. The category page calls this very
 * function on the same days, which is what keeps its number equal to the
 * dashboard's.
 */
export function averageDailyValue(
  days: TableDay[],
  categoryId: number,
  fieldId: number
): number | null {
  const values = days
    .map((day) => dailyValue(day, categoryId, fieldId))
    .filter((value): value is number => value !== null);
  if (values.length === 0) return null;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function relativeLuminance(hex: string): number | null {
  const match = HEX_COLOR.exec(hex);
  if (match === null) return null;
  const channels = [0, 2, 4].map((start) => parseInt(match[1].slice(start, start + 2), 16) / 255);
  return channels.reduce((sum, channel, index) => {
    const linear =
      channel <= SRGB_LINEAR_CUTOFF ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
    return sum + LUMINANCE_WEIGHTS[index] * linear;
  }, 0);
}

/** Whether `color` stays visible as a thin line on the dashboard card. */
function isReadableOnCard(color: string): boolean {
  const own = relativeLuminance(color);
  const surface = relativeLuminance(CARD_SURFACE);
  if (own === null || surface === null) return false;
  const [lighter, darker] = own > surface ? [own, surface] : [surface, own];
  return (lighter + CONTRAST_FLARE) / (darker + CONTRAST_FLARE) >= MIN_GRAPHIC_CONTRAST;
}

/**
 * The block's rows, computed from one table response.
 *
 * Selection is automatic - the active categories with a number field that have
 * the most entries in the period - because a manual "show on dashboard" flag
 * would be a third visibility flag next to `is_active` and `show_in_today`.
 */
export function buildDashboardTrends(
  categories: Category[],
  days: TableDay[],
  period: TrendPeriod,
  now: Date = new Date()
): DashboardTrend[] {
  const dates = datesEndingToday(period * 2, now);
  const byDate = new Map(days.map((day) => [day.date, day]));
  const windowDays = (window: string[]): TableDay[] =>
    window.map((date) => byDate.get(date) ?? { date, cells: [] });
  const previous = windowDays(dates.slice(0, period));
  const current = windowDays(dates.slice(period));

  const ranked = categories
    .filter((category) => category.is_active)
    .flatMap((category) => {
      const field = firstNumberField(category);
      if (field === undefined) return [];
      const average = averageDailyValue(current, category.id, field.id);
      if (average === null) return [];
      const entryCount = current.reduce(
        (sum, day) =>
          sum +
          day.cells
            .filter((cell) => cell.category_id === category.id && cell.field_id === field.id)
            .reduce((cellSum, cell) => cellSum + cell.entry_count, 0),
        0
      );
      return [{ category, field, average, entryCount }];
    })
    .sort((a, b) => b.entryCount - a.entryCount || a.category.id - b.category.id)
    .slice(0, MAX_TREND_CATEGORIES);

  return ranked.map(({ category, field, average }, rank) => {
    const previousAverage = averageDailyValue(previous, category.id, field.id);
    const color = category.color;
    return {
      categoryId: category.id,
      categoryName: category.name,
      icon: category.icon ?? null,
      unit: field.unit ?? null,
      color:
        color !== undefined && isReadableOnCard(color)
          ? color
          : SERIES_COLORS[rank % SERIES_COLORS.length],
      average,
      deltaPercent:
        previousAverage === null || previousAverage === 0
          ? null
          : ((average - previousAverage) / Math.abs(previousAverage)) * PERCENT,
      sparkline: current.map((day) => ({
        date: day.date,
        value: dailyValue(day, category.id, field.id),
      })),
    };
  });
}

/** «38.6 reps», or the bare number when the field has no unit. */
export function formatTrendAverage(average: number | null, unit: string | null): string {
  if (average === null) return '—';
  return formatValue(Number(average.toFixed(AVERAGE_DECIMALS)), unit);
}

/** The two halves of «+18 % vs prev 30d»; a change that rounds to zero carries no sign. */
export function formatTrendDeltaParts(
  deltaPercent: number | null,
  period: TrendPeriod
): { change: string; comparison: string } {
  const comparison = `vs prev ${period}d`;
  if (deltaPercent === null) return { change: '—', comparison };
  const rounded = Math.round(deltaPercent);
  return { change: `${rounded > 0 ? '+' : ''}${rounded} %`, comparison };
}

export interface SparklinePoint {
  x: number;
  y: number;
}

/**
 * Polyline segments for the sparkline, one per run of days with a value, so a
 * missing day is a gap in the line and not a drop to zero.
 */
export function sparklineSegments(
  points: TrendPoint[],
  width: number,
  height: number
): SparklinePoint[][] {
  const values = points.flatMap((point) => (point.value === null ? [] : [point.value]));
  if (values.length === 0) return [];
  const minimum = Math.min(...values);
  const range = Math.max(...values) - minimum;
  const lastIndex = Math.max(points.length - 1, 1);

  const segments: SparklinePoint[][] = [];
  let run: SparklinePoint[] = [];
  points.forEach((point, index) => {
    if (point.value === null) {
      if (run.length > 0) segments.push(run);
      run = [];
      return;
    }
    run.push({
      x: (index / lastIndex) * width,
      y: range === 0 ? height / 2 : height - ((point.value - minimum) / range) * height,
    });
  });
  if (run.length > 0) segments.push(run);
  return segments;
}
