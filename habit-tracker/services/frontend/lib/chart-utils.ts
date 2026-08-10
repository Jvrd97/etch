// [review:need-review] PHASE-01/59-previousday-mixed-utc-local, PHASE-01/73-category-field-reorder
// summary: chart pure helpers - cumulate() prefix sums; checklist bar data; previousDay stepped on the bare calendar (no timezone) and per-field current streaks

import type { Field, TableDay } from './api';
import type { ChartPoint } from './chart-data';
import { ISO_DATE_PAD } from './date';
import { orderedFields } from './today-categories';

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
  return orderedFields(fields).filter((f) => f.field_type === 'boolean');
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

/**
 * Previous calendar day of a `YYYY-MM-DD` string.
 *
 * A bare ISO date carries no timezone, so neither does this: the day is stepped
 * back on the proleptic Gregorian calendar itself, via a `Date` pinned to UTC
 * for its month-length and leap-year knowledge and read back in the same UTC
 * frame. Formatting through the local-calendar `toISODate` would reintroduce
 * the offset and, west of Greenwich, land on the day before the one asked for.
 */
export function previousDay(isoDate: string): string {
  const [year, month, day] = isoDate.split('-').map(Number);
  const cursor = new Date(Date.UTC(year, month - 1, day));
  cursor.setUTCDate(cursor.getUTCDate() - 1);
  const steppedMonth = String(cursor.getUTCMonth() + 1).padStart(ISO_DATE_PAD, '0');
  const steppedDay = String(cursor.getUTCDate()).padStart(ISO_DATE_PAD, '0');
  return `${cursor.getUTCFullYear()}-${steppedMonth}-${steppedDay}`;
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
