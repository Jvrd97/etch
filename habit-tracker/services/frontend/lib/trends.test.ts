// [review:need-review] #78
// summary: tests for the dashboard trend maths - period windows, top-4 selection, daily average, delta sign and rounding, sparkline gaps and geometry, contrast fallback

import { describe, expect, it } from 'bun:test';
import type { Category, Field, TableCell, TableDay } from './api';
import { SERIES_COLORS } from './chart-data';
import { todayISO } from './date';
import {
  DEFAULT_TREND_PERIOD,
  TREND_PERIODS,
  averageDailyValue,
  buildDashboardTrends,
  chartPeriodFor,
  formatTrendAverage,
  formatTrendDeltaParts,
  parseTrendPeriod,
  sparklineSegments,
  trendDateRange,
} from './trends';

const TIMESTAMP = '2026-09-01T00:00:00Z';
/** Local noon, so the calendar date never depends on the timezone of the runner. */
const NOW = new Date(2026, 8, 30, 12, 0, 0);
/**
 * Today as the code under test reads it. Other suites pin `todayISO` for the
 * whole run, so the windows are anchored here instead of on a literal date.
 */
const TODAY = todayISO(NOW);

/** Field id is `categoryId * 10 + index`, so the cells in a test read off the ids. */
function numberField(categoryId: number, index: number, overrides: Partial<Field> = {}): Field {
  return {
    id: categoryId * 10 + index,
    category_id: categoryId,
    name: `Number ${index}`,
    field_type: 'number',
    is_required: false,
    order: index,
    created_at: TIMESTAMP,
    updated_at: TIMESTAMP,
    ...overrides,
  };
}

function category(id: number, overrides: Partial<Category> = {}): Category {
  return {
    id,
    name: `Category ${id}`,
    display_mode: 'form',
    streak_mode: 'build',
    is_active: true,
    created_at: TIMESTAMP,
    updated_at: TIMESTAMP,
    fields: [numberField(id, 1, { unit: 'reps' })],
    ...overrides,
  };
}

function cell(categoryId: number, value: string | null, entryCount = 1, index = 1): TableCell {
  return {
    category_id: categoryId,
    field_id: categoryId * 10 + index,
    aggregated_value: value,
    entry_count: entryCount,
  };
}

function day(date: string, ...cells: TableCell[]): TableDay {
  return { date, cells };
}

/** ISO date `offset` days before TODAY (0 is today). */
function daysAgo(offset: number): string {
  const [year, month, dayOfMonth] = TODAY.split('-').map(Number);
  const date = new Date(year, month - 1, dayOfMonth - offset);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

describe('trend periods', () => {
  it('offers the three periods and defaults to thirty days', () => {
    expect(TREND_PERIODS).toEqual([7, 30, 90]);
    expect(DEFAULT_TREND_PERIOD).toBe(30);
  });

  it('accepts only the offered periods from a query string value', () => {
    expect(parseTrendPeriod('7')).toBe(7);
    expect(parseTrendPeriod('90')).toBe(90);
    expect(parseTrendPeriod('14')).toBeNull();
    expect(parseTrendPeriod('all')).toBeNull();
    expect(parseTrendPeriod(null)).toBeNull();
  });

  it('maps a trend period to the chart period of the same length', () => {
    expect(chartPeriodFor(7)).toBe('7d');
    expect(chartPeriodFor(30)).toBe('30d');
    expect(chartPeriodFor(90)).toBe('90d');
  });

  it('asks for the current and the previous period in one range ending today', () => {
    expect(trendDateRange(30, NOW)).toEqual({ dateFrom: daysAgo(59), dateTo: TODAY });
    expect(trendDateRange(7, NOW)).toEqual({ dateFrom: daysAgo(13), dateTo: TODAY });
  });

  it('keeps even the longest range inside the 366 days GET /table accepts', () => {
    const { dateFrom, dateTo } = trendDateRange(90, NOW);
    const length = (Date.parse(dateTo) - Date.parse(dateFrom)) / 86_400_000 + 1;
    expect(length).toBe(180);
  });
});

describe('averageDailyValue', () => {
  it('averages the daily sums of the days that have a value, zero included', () => {
    const days = [
      day('2026-09-28', cell(1, '0')),
      day('2026-09-29', cell(1, '9')),
      day('2026-09-30'),
    ];
    expect(averageDailyValue(days, 1, 11)).toBe(4.5);
  });

  it('ignores null and non-numeric cells and reports null when nothing is left', () => {
    const days = [day('2026-09-28', cell(1, null)), day('2026-09-29', cell(1, 'bad'))];
    expect(averageDailyValue(days, 1, 11)).toBeNull();
    expect(averageDailyValue([], 1, 11)).toBeNull();
  });

  it('reads only the requested category and field', () => {
    const days = [day('2026-09-30', cell(1, '10'), cell(2, '99'), cell(1, '77', 1, 2))];
    expect(averageDailyValue(days, 1, 11)).toBe(10);
  });
});

describe('buildDashboardTrends: selection', () => {
  function windowWith(counts: Record<number, number>): TableDay[] {
    return [
      day(
        daysAgo(1),
        ...Object.entries(counts).map(([id, count]) => cell(Number(id), '10', count))
      ),
    ];
  }

  it('keeps the four categories with the most entries in the period, most first', () => {
    const categories = [1, 2, 3, 4, 5, 6].map((id) => category(id));
    const days = windowWith({ 1: 3, 2: 9, 3: 1, 4: 5, 5: 7, 6: 2 });

    const trends = buildDashboardTrends(categories, days, 30, NOW);

    expect(trends.map((trend) => trend.categoryId)).toEqual([2, 5, 4, 1]);
  });

  it('breaks a tie by category id so the block does not reshuffle between loads', () => {
    const categories = [category(3), category(1), category(2)];
    const trends = buildDashboardTrends(categories, windowWith({ 1: 4, 2: 4, 3: 4 }), 30, NOW);
    expect(trends.map((trend) => trend.categoryId)).toEqual([1, 2, 3]);
  });

  it('counts only the current period, not the previous one used for the delta', () => {
    const days = [
      day(daysAgo(40), cell(1, '10', 50)),
      day(daysAgo(2), cell(1, '10', 1), cell(2, '10', 2)),
    ];
    const trends = buildDashboardTrends([category(1), category(2)], days, 30, NOW);
    expect(trends.map((trend) => trend.categoryId)).toEqual([2, 1]);
  });

  it('skips inactive categories and categories without a number field', () => {
    const textOnly = category(3, {
      fields: [numberField(3, 1, { field_type: 'text' })],
    });
    const categories = [category(1, { is_active: false }), category(2), textOnly];
    const trends = buildDashboardTrends(categories, windowWith({ 1: 9, 2: 1, 3: 9 }), 30, NOW);
    expect(trends.map((trend) => trend.categoryId)).toEqual([2]);
  });

  it('skips a category whose entries carry no numeric value in the period', () => {
    const days = [day(daysAgo(1), cell(1, null, 4), cell(2, '5', 1))];
    const trends = buildDashboardTrends([category(1), category(2)], days, 30, NOW);
    expect(trends.map((trend) => trend.categoryId)).toEqual([2]);
  });

  it('returns fewer than four rows, or none, when little qualifies', () => {
    expect(buildDashboardTrends([category(1)], windowWith({ 1: 1 }), 30, NOW)).toHaveLength(1);
    expect(buildDashboardTrends([category(1)], [], 30, NOW)).toEqual([]);
    expect(buildDashboardTrends([], windowWith({ 1: 1 }), 30, NOW)).toEqual([]);
  });

  it('uses the first number field by order and its unit', () => {
    const multi = category(1, {
      fields: [
        numberField(1, 2, { order: 2, unit: 'kg' }),
        numberField(1, 1, { order: 1, unit: 'reps' }),
      ],
    });
    const days = [day(daysAgo(1), cell(1, '40', 1, 1), cell(1, '80', 1, 2))];

    const [trend] = buildDashboardTrends([multi], days, 30, NOW);

    expect(trend?.unit).toBe('reps');
    expect(trend?.average).toBe(40);
  });

  it('carries a missing unit as null', () => {
    const bare = category(1, { fields: [numberField(1, 1)] });
    const [trend] = buildDashboardTrends([bare], windowWith({ 1: 1 }), 30, NOW);
    expect(trend?.unit).toBeNull();
  });
});

describe('buildDashboardTrends: numbers', () => {
  it('averages the current period and keeps a zero average a number', () => {
    const days = [day(daysAgo(2), cell(1, '0')), day(daysAgo(1), cell(1, '0'))];
    const [trend] = buildDashboardTrends([category(1)], days, 30, NOW);
    expect(trend?.average).toBe(0);
  });

  it('gives one sparkline point per day of the period, oldest first, null for a missing day', () => {
    const days = [day(daysAgo(1), cell(1, '8')), day(daysAgo(0), cell(1, '0'))];
    const [trend] = buildDashboardTrends([category(1)], days, 7, NOW);

    expect(trend?.sparkline).toHaveLength(7);
    expect(trend?.sparkline[0]).toEqual({ date: daysAgo(6), value: null });
    expect(trend?.sparkline[5]).toEqual({ date: daysAgo(1), value: 8 });
    expect(trend?.sparkline[6]).toEqual({ date: daysAgo(0), value: 0 });
  });

  it('ignores days outside the window', () => {
    const days = [day(daysAgo(1), cell(1, '10')), day(daysAgo(400), cell(1, '1000'))];
    const [trend] = buildDashboardTrends([category(1)], days, 30, NOW);
    expect(trend?.average).toBe(10);
  });

  it('compares with the previous period of the same length', () => {
    const days = [
      day(daysAgo(1), cell(1, '12')),
      day(daysAgo(10), cell(1, '10')),
      day(daysAgo(31), cell(1, '10')),
    ];
    const [trend] = buildDashboardTrends([category(1)], days, 30, NOW);
    // current: (12 + 10) / 2 = 11; previous: 10 -> +10 %
    expect(trend?.average).toBe(11);
    expect(trend?.deltaPercent).toBeCloseTo(10);
  });

  it('puts the 7-day boundary between day 7 and day 8 back', () => {
    const days = [day(daysAgo(6), cell(1, '10')), day(daysAgo(7), cell(1, '5'))];
    const [trend] = buildDashboardTrends([category(1)], days, 7, NOW);
    expect(trend?.average).toBe(10);
    expect(trend?.deltaPercent).toBeCloseTo(100);
  });

  it('has no delta when the previous period holds no data', () => {
    const [trend] = buildDashboardTrends([category(1)], [day(daysAgo(1), cell(1, '10'))], 30, NOW);
    expect(trend?.deltaPercent).toBeNull();
  });

  it('has no delta when the previous average is zero, instead of dividing by it', () => {
    const days = [day(daysAgo(1), cell(1, '10')), day(daysAgo(40), cell(1, '0'))];
    const [trend] = buildDashboardTrends([category(1)], days, 30, NOW);
    expect(trend?.deltaPercent).toBeNull();
  });

  it('shows a fall as a negative delta', () => {
    const days = [day(daysAgo(1), cell(1, '0')), day(daysAgo(40), cell(1, '10'))];
    const [trend] = buildDashboardTrends([category(1)], days, 30, NOW);
    expect(trend?.deltaPercent).toBe(-100);
  });

  it('keeps the direction of the change when the previous average is negative', () => {
    const days = [day(daysAgo(1), cell(1, '-1')), day(daysAgo(40), cell(1, '-2'))];
    const [trend] = buildDashboardTrends([category(1)], days, 30, NOW);
    expect(trend?.deltaPercent).toBe(50);
  });
});

describe('buildDashboardTrends: color', () => {
  const onlyDay = [day(daysAgo(1), cell(1, '1'))];

  it('keeps the category color when it is readable on the card', () => {
    const [trend] = buildDashboardTrends([category(1, { color: '#ff6b6b' })], onlyDay, 30, NOW);
    expect(trend?.color).toBe('#ff6b6b');
  });

  it('falls back to the series palette when the color would vanish on the card', () => {
    const [dark] = buildDashboardTrends([category(1, { color: '#1a1a1a' })], onlyDay, 30, NOW);
    const [malformed] = buildDashboardTrends([category(1, { color: 'teal' })], onlyDay, 30, NOW);
    expect(dark?.color).toBe(SERIES_COLORS[0]);
    expect(malformed?.color).toBe(SERIES_COLORS[0]);
  });

  it('uses the palette by rank for categories without a color', () => {
    const days = [day(daysAgo(1), cell(1, '1', 5), cell(2, '1', 3))];
    const trends = buildDashboardTrends([category(1), category(2)], days, 30, NOW);
    expect(trends.map((trend) => trend.color)).toEqual([SERIES_COLORS[0], SERIES_COLORS[1]]);
  });
});

describe('formatting', () => {
  it('rounds the average to one decimal and appends the unit', () => {
    expect(formatTrendAverage(38.64, 'reps')).toBe('38.6 reps');
    expect(formatTrendAverage(1250, 'ml')).toBe('1250 ml');
    expect(formatTrendAverage(0, 'reps')).toBe('0 reps');
  });

  it('shows a bare number when the field has no unit', () => {
    expect(formatTrendAverage(2.5, null)).toBe('2.5');
  });

  it('shows a dash instead of an average that does not exist', () => {
    expect(formatTrendAverage(null, 'reps')).toBe('—');
  });

  it('signs the change and names the comparison period', () => {
    expect(formatTrendDeltaParts(18.2, 30)).toEqual({ change: '+18 %', comparison: 'vs prev 30d' });
    expect(formatTrendDeltaParts(-8.4, 7)).toEqual({ change: '-8 %', comparison: 'vs prev 7d' });
    expect(formatTrendDeltaParts(100, 90)).toEqual({ change: '+100 %', comparison: 'vs prev 90d' });
  });

  it('does not sign a change that rounds to zero', () => {
    expect(formatTrendDeltaParts(0, 30).change).toBe('0 %');
    expect(formatTrendDeltaParts(0.4, 30).change).toBe('0 %');
    expect(formatTrendDeltaParts(-0.4, 30).change).toBe('0 %');
  });

  it('shows a dash when there is nothing to compare with', () => {
    expect(formatTrendDeltaParts(null, 7)).toEqual({ change: '—', comparison: 'vs prev 7d' });
  });
});

describe('sparklineSegments', () => {
  it('scales values into the box, highest at the top, and splits at a gap', () => {
    const points = [
      { date: 'a', value: 0 },
      { date: 'b', value: 10 },
      { date: 'c', value: null },
      { date: 'd', value: 5 },
    ];
    expect(sparklineSegments(points, 30, 10)).toEqual([
      [
        { x: 0, y: 10 },
        { x: 10, y: 0 },
      ],
      [{ x: 30, y: 5 }],
    ]);
  });

  it('draws a flat series in the middle of the box', () => {
    const points = [
      { date: 'a', value: 3 },
      { date: 'b', value: 3 },
    ];
    expect(sparklineSegments(points, 10, 8)).toEqual([
      [
        { x: 0, y: 4 },
        { x: 10, y: 4 },
      ],
    ]);
  });

  it('draws nothing when no day has a value', () => {
    expect(sparklineSegments([{ date: 'a', value: null }], 10, 8)).toEqual([]);
    expect(sparklineSegments([], 10, 8)).toEqual([]);
  });
});
