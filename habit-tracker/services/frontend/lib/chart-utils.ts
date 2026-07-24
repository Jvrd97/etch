// [review:need-review] PHASE-01/23-checklist-bar-streaks
// summary: chart pure helpers - cumulate() prefix sums; checklist bar data (true-count per day) and per-field current streaks

import type { Field, TableDay } from './api';
import type { ChartPoint } from './chart-data';
import { toISODate } from './date';

/**
 * Running (prefix) sum for every series key, computed independently per line.
 * Null cells stay null (gap in the line) and leave the running total unchanged,
 * so the drawn curve is monotonically non-decreasing. Input is not mutated.
 */
export function cumulate(points: ChartPoint[]): ChartPoint[] {
  const totals = new Map<string, number>();
  return points.map((point) => {
    const out: ChartPoint = { date: point.date };
    for (const [key, value] of Object.entries(point)) {
      if (key === 'date') continue;
      if (typeof value !== 'number') {
        out[key] = value;
        continue;
      }
      const total = (totals.get(key) ?? 0) + value;
      totals.set(key, total);
      out[key] = total;
    }
    return out;
  });
}

/** Cell value the table API uses for a checked boolean field. */
const TRUE_VALUE = 'true';

export interface ChecklistBarPoint {
  date: string;
  done: number;
}

/** Boolean fields of a checklist category, in field order. */
export function booleanFields(fields: Field[]): Field[] {
  return fields
    .filter((f) => f.field_type === 'boolean')
    .sort((a, b) => a.order - b.order || a.id - b.id);
}

/**
 * One bar point per day: how many boolean fields of the category were checked
 * ("X out of N"). Missing cells and non-"true" values count as not done.
 */
export function buildChecklistBarData(
  days: TableDay[],
  categoryId: number,
  fields: Field[]
): ChecklistBarPoint[] {
  const boolIds = new Set(booleanFields(fields).map((f) => f.id));
  return days.map((day) => ({
    date: day.date,
    done: day.cells.filter(
      (c) =>
        c.category_id === categoryId &&
        boolIds.has(c.field_id) &&
        c.aggregated_value === TRUE_VALUE
    ).length,
  }));
}

const MS_PER_DAY = 24 * 60 * 60 * 1000;

/** Previous calendar day of an ISO date string (UTC arithmetic). */
function previousDay(isoDate: string): string {
  return toISODate(new Date(Date.parse(`${isoDate}T00:00:00Z`) - MS_PER_DAY));
}

/**
 * Consecutive days with a true value for one boolean field, counted from today
 * backwards. A day without a true value breaks the streak, except today itself:
 * an unchecked today is treated as pending, so a streak ending yesterday still
 * counts until the day is over.
 */
export function currentStreak(
  days: TableDay[],
  categoryId: number,
  fieldId: number,
  today: string
): number {
  const doneDates = new Set(
    days
      .filter((d) =>
        d.cells.some(
          (c) =>
            c.category_id === categoryId &&
            c.field_id === fieldId &&
            c.aggregated_value === TRUE_VALUE
        )
      )
      .map((d) => d.date)
  );
  let cursor = doneDates.has(today) ? today : previousDay(today);
  let streak = 0;
  while (doneDates.has(cursor)) {
    streak += 1;
    cursor = previousDay(cursor);
  }
  return streak;
}
