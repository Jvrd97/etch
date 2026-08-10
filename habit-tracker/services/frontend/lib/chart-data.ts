// [review:need-review] PHASE-01/23-checklist-bar-streaks, PHASE-01/73-category-field-reorder
// summary: pure helpers for the category chart - series/axis/unit assignment, cell parsing, per-day points; sliceByPeriod made generic for checklist bar points

import type { Field, TableDay } from './api';
import { toISODate } from './date';
import { orderedFields } from './today-categories';

export type ChartPeriod = '7d' | '30d' | '90d' | 'all';

export const CHART_PERIODS: readonly ChartPeriod[] = ['7d', '30d', '90d', 'all'];

export const PERIOD_LABELS: Record<ChartPeriod, string> = {
  '7d': '7 days',
  '30d': '30 days',
  '90d': '90 days',
  all: 'All',
};

/** Backend caps GET /table at 366 days; fetch a year and slice client-side. */
export const MAX_CHART_DAYS = 365;

const PERIOD_DAYS: Record<Exclude<ChartPeriod, 'all'>, number> = {
  '7d': 7,
  '30d': 30,
  '90d': 90,
};

const TIME_UNIT = 'min';
const MINUTES_PER_HOUR = 60;
const SECONDS_PER_MINUTE = 60;

/** Dark-surface categorical palette, validated with dataviz six-checks (surface #1a1a1a). */
export const SERIES_COLORS: readonly string[] = [
  '#65a30d',
  '#0284c7',
  '#b45309',
  '#9333ea',
];

export interface ChartSeries {
  key: string;
  fieldId: number;
  name: string;
  unit: string;
  axis: 'left' | 'right';
  color: string;
}

export interface ChartPoint {
  date: string;
  [seriesKey: string]: string | number | null;
}

type ChartableFieldType = 'number' | 'time';

/** Fields that can be plotted as lines, in field order. */
export function chartableFields(fields: Field[]): Field[] {
  return orderedFields(fields).filter(
    (f) => f.field_type === 'number' || f.field_type === 'time'
  );
}

/** Unit label: time fields are minutes; number fields use "(unit)" from the name if present. */
function fieldUnit(field: Field): string {
  if (field.field_type === 'time') return TIME_UNIT;
  const match = field.name.match(/\(([^)]+)\)\s*$/);
  return match ? match[1].trim() : field.name;
}

/**
 * Build line series for chartable fields. The first distinct unit goes to the
 * left Y axis; every other unit shares the right one (ticket #20: two axes max).
 */
export function buildSeries(fields: Field[]): ChartSeries[] {
  const plottable = chartableFields(fields);
  let leftUnit: string | null = null;
  return plottable.map((field, index) => {
    const unit = fieldUnit(field);
    if (leftUnit === null) leftUnit = unit;
    return {
      key: `f${field.id}`,
      fieldId: field.id,
      name: field.name,
      unit,
      axis: unit === leftUnit ? 'left' : 'right',
      color: SERIES_COLORS[index % SERIES_COLORS.length],
    };
  });
}

/** Parse an aggregated cell value into a plottable number (time -> minutes). */
export function parseCellValue(
  fieldType: ChartableFieldType,
  raw: string | null
): number | null {
  if (raw === null) return null;
  if (fieldType === 'number') {
    const value = Number(raw);
    return Number.isFinite(value) && raw.trim() !== '' ? value : null;
  }
  const match = raw.match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?$/);
  if (!match) return null;
  const hours = Number(match[1]);
  const minutes = Number(match[2]);
  const seconds = match[3] !== undefined ? Number(match[3]) : 0;
  return hours * MINUTES_PER_HOUR + minutes + seconds / SECONDS_PER_MINUTE;
}

/** One chart point per day; missing cells become null (gap in the line). */
export function buildChartData(
  days: TableDay[],
  categoryId: number,
  fields: Field[]
): ChartPoint[] {
  const plottable = chartableFields(fields);
  return days.map((day) => {
    const point: ChartPoint = { date: day.date };
    for (const field of plottable) {
      const cell = day.cells.find(
        (c) => c.category_id === categoryId && c.field_id === field.id
      );
      point[`f${field.id}`] = parseCellValue(
        // safe: chartableFields keeps only number/time fields
        field.field_type as ChartableFieldType,
        cell?.aggregated_value ?? null
      );
    }
    return point;
  });
}

/** Widest fetch window: MAX_CHART_DAYS ending today (backend caps ranges at 366 days). */
export function chartDateRange(today: Date): { from: string; to: string } {
  const from = new Date(today);
  from.setUTCDate(from.getUTCDate() - (MAX_CHART_DAYS - 1));
  return { from: toISODate(from), to: toISODate(today) };
}

/** Keep the last N per-day points for the selected period ('all' keeps everything). */
export function sliceByPeriod<T>(points: T[], period: ChartPeriod): T[] {
  if (period === 'all') return points;
  return points.slice(-PERIOD_DAYS[period]);
}
