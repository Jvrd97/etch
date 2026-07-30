// [review:need-review] PHASE-01/59-previousday-mixed-utc-local
// summary: unit tests for chart-utils - cumulate() running sums; checklist bar data; previousDay and currentStreak pinned to western timezones

import { describe, expect, it } from 'bun:test';
import type { Field, TableDay } from './api';
import type { ChartPoint } from './chart-data';
import { buildChecklistBarData, cumulate, currentStreak, previousDay } from './chart-utils';

describe('cumulate', () => {
  it('returns an empty array for an empty series', () => {
    expect(cumulate([])).toEqual([]);
  });

  it('produces a monotonically non-decreasing running sum for one line', () => {
    const points: ChartPoint[] = [
      { date: '2026-07-01', f1: 2 },
      { date: '2026-07-02', f1: 3 },
      { date: '2026-07-03', f1: 1 },
    ];
    expect(cumulate(points)).toEqual([
      { date: '2026-07-01', f1: 2 },
      { date: '2026-07-02', f1: 5 },
      { date: '2026-07-03', f1: 6 },
    ]);
  });

  it('keeps null gaps as null without breaking the running total', () => {
    const points: ChartPoint[] = [
      { date: '2026-07-01', f1: null },
      { date: '2026-07-02', f1: 4 },
      { date: '2026-07-03', f1: null },
      { date: '2026-07-04', f1: 6 },
    ];
    expect(cumulate(points)).toEqual([
      { date: '2026-07-01', f1: null },
      { date: '2026-07-02', f1: 4 },
      { date: '2026-07-03', f1: null },
      { date: '2026-07-04', f1: 10 },
    ]);
  });

  it('accumulates multiple lines independently', () => {
    const points: ChartPoint[] = [
      { date: '2026-07-01', f1: 1, f2: 10 },
      { date: '2026-07-02', f1: 2, f2: null },
      { date: '2026-07-03', f1: 3, f2: 30 },
    ];
    expect(cumulate(points)).toEqual([
      { date: '2026-07-01', f1: 1, f2: 10 },
      { date: '2026-07-02', f1: 3, f2: null },
      { date: '2026-07-03', f1: 6, f2: 40 },
    ]);
  });

  it('does not mutate the input points', () => {
    const points: ChartPoint[] = [
      { date: '2026-07-01', f1: 2 },
      { date: '2026-07-02', f1: 3 },
    ];
    cumulate(points);
    expect(points[1].f1).toBe(3);
  });
});

function makeBoolField(
  overrides: Partial<Field> & Pick<Field, 'id' | 'name'>
): Field {
  return {
    category_id: 1,
    field_type: 'boolean',
    is_required: false,
    order: 0,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

const vitaminD = makeBoolField({ id: 1, name: 'Vitamin D', order: 0 });
const magnesium = makeBoolField({ id: 2, name: 'Magnesium', order: 1 });
const omega3 = makeBoolField({ id: 3, name: 'Omega 3', order: 2 });
const notesField = makeBoolField({ id: 4, name: 'Notes', field_type: 'text', order: 3 });

function day(date: string, trueFieldIds: number[], categoryId = 1): TableDay {
  return {
    date,
    cells: trueFieldIds.map((fieldId) => ({
      category_id: categoryId,
      field_id: fieldId,
      aggregated_value: 'true',
      entry_count: 1,
    })),
  };
}

describe('buildChecklistBarData', () => {
  it('returns an empty array for empty history', () => {
    expect(buildChecklistBarData([], 1, [vitaminD, magnesium])).toEqual([]);
  });

  it('counts true boolean cells per day, missing cells count as not done', () => {
    const days: TableDay[] = [
      day('2026-07-01', [1, 2, 3]),
      day('2026-07-02', [2]),
      day('2026-07-03', []),
    ];
    expect(buildChecklistBarData(days, 1, [vitaminD, magnesium, omega3])).toEqual([
      { date: '2026-07-01', done: 3 },
      { date: '2026-07-02', done: 1 },
      { date: '2026-07-03', done: 0 },
    ]);
  });

  it('ignores non-boolean fields, other categories, and false cells', () => {
    const days: TableDay[] = [
      {
        date: '2026-07-01',
        cells: [
          { category_id: 1, field_id: 1, aggregated_value: 'true', entry_count: 1 },
          { category_id: 1, field_id: 2, aggregated_value: 'false', entry_count: 1 },
          { category_id: 1, field_id: 4, aggregated_value: 'true', entry_count: 1 },
          { category_id: 9, field_id: 3, aggregated_value: 'true', entry_count: 1 },
        ],
      },
    ];
    expect(
      buildChecklistBarData(days, 1, [vitaminD, magnesium, omega3, notesField])
    ).toEqual([{ date: '2026-07-01', done: 1 }]);
  });
});

describe('previousDay', () => {
  /**
   * Runs `body` with the process pinned to `tz`. The zones used below sit west
   * of Greenwich on purpose: a negative offset is what turned UTC midnight into
   * the *previous* local date and made the old mixed UTC/local arithmetic skip
   * a day.
   */
  function inTimezone(tz: string, body: () => void): void {
    const original = process.env.TZ;
    process.env.TZ = tz;
    try {
      body();
    } finally {
      process.env.TZ = original;
    }
  }

  it('steps back one day inside a month', () => {
    expect(previousDay('2026-07-22')).toBe('2026-07-21');
  });

  it('steps back across a month boundary', () => {
    expect(previousDay('2026-07-01')).toBe('2026-06-30');
  });

  it('steps back across a year boundary', () => {
    expect(previousDay('2026-01-01')).toBe('2025-12-31');
  });

  it('steps back onto a leap day', () => {
    expect(previousDay('2024-03-01')).toBe('2024-02-29');
  });

  it('gives the same calendar date west of Greenwich', () => {
    inTimezone('America/Los_Angeles', () => {
      expect(previousDay('2026-07-22')).toBe('2026-07-21');
      expect(previousDay('2026-01-01')).toBe('2025-12-31');
    });
  });

  it('gives the same calendar date on a far-western zone', () => {
    inTimezone('Pacific/Midway', () => {
      expect(previousDay('2026-07-22')).toBe('2026-07-21');
    });
  });
});

describe('currentStreak', () => {
  const TODAY = '2026-07-22';

  it('is 0 for empty history', () => {
    expect(currentStreak([], 1, 1, TODAY)).toBe(0);
  });

  it('is 0 when neither today nor yesterday has a true value', () => {
    const days: TableDay[] = [day('2026-07-19', [1])];
    expect(currentStreak(days, 1, 1, TODAY)).toBe(0);
  });

  it('is 1 when only today is done', () => {
    const days: TableDay[] = [day(TODAY, [1])];
    expect(currentStreak(days, 1, 1, TODAY)).toBe(1);
  });

  it('counts N consecutive days ending today', () => {
    const days: TableDay[] = [
      day('2026-07-19', [1]),
      day('2026-07-20', [1]),
      day('2026-07-21', [1]),
      day(TODAY, [1]),
    ];
    expect(currentStreak(days, 1, 1, TODAY)).toBe(4);
  });

  it('breaks the streak at a day without a true value', () => {
    const days: TableDay[] = [
      day('2026-07-18', [1]),
      day('2026-07-19', [1]),
      day('2026-07-20', []),
      day('2026-07-21', [1]),
      day(TODAY, [1]),
    ];
    expect(currentStreak(days, 1, 1, TODAY)).toBe(2);
  });

  it('keeps yesterday-ending streak alive while today is still pending', () => {
    const days: TableDay[] = [day('2026-07-20', [1]), day('2026-07-21', [1])];
    expect(currentStreak(days, 1, 1, TODAY)).toBe(2);
  });

  it('ignores true values of other fields and categories', () => {
    const days: TableDay[] = [day(TODAY, [2]), day('2026-07-21', [1], 9)];
    expect(currentStreak(days, 1, 1, TODAY)).toBe(0);
  });

  it('walks consecutive days west of Greenwich too', () => {
    const original = process.env.TZ;
    process.env.TZ = 'America/Los_Angeles';
    try {
      const days: TableDay[] = [
        day('2026-07-20', [1]),
        day('2026-07-21', [1]),
        day(TODAY, [1]),
      ];
      expect(currentStreak(days, 1, 1, TODAY)).toBe(3);
    } finally {
      process.env.TZ = original;
    }
  });
});
