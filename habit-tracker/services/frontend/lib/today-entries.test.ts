// [review:need-review] PHASE-01/63-today-card-tap-and-visibility
// summary: unit tests for Today entry state — number totals, optimistic merge, today's entry lookup for the card-tap editor, checked map, optimistic flip + rollback, streak degradation to null

import { describe, expect, it } from 'bun:test';
import type { Category, CategoryStreak, Entry, Field } from './api';
import {
  buildCheckedMap,
  isFieldChecked,
  loadStreakMap,
  numberFieldSum,
  setFieldChecked,
  todayEntryForCategory,
  type CheckedMap,
} from './today-entries';

function field(overrides: Partial<Field>): Field {
  return {
    id: 1,
    category_id: 1,
    name: 'Field',
    field_type: 'text',
    is_required: false,
    order: 0,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

function category(overrides: Partial<Category>): Category {
  return {
    id: 1,
    name: 'Category',
    display_mode: 'form',
    streak_mode: 'build',
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    fields: [],
    ...overrides,
  };
}

function entry(categoryId: number, values: { field_id: number; value: string }[]): Entry {
  return {
    id: categoryId * 100,
    category_id: categoryId,
    entry_date: '2026-07-24',
    created_at: '2026-07-24T00:00:00Z',
    updated_at: '2026-07-24T00:00:00Z',
    values: values.map((v, index) => ({
      id: index + 1,
      entry_id: categoryId * 100,
      field_id: v.field_id,
      value: v.value,
    })),
  };
}

function streak(categoryId: number): CategoryStreak {
  return {
    category_id: categoryId,
    streak_mode: 'avoid',
    current_streak: 3,
    best_streak: 9,
    last_relapse_date: null,
  };
}

describe('numberFieldSum', () => {
  it('adds up the field across every entry of the category', () => {
    const entries = [
      entry(1, [{ field_id: 10, value: '2' }]),
      entry(1, [{ field_id: 10, value: '3.5' }]),
    ];
    expect(numberFieldSum(entries, 1, 10)).toBe(5.5);
  });

  it('ignores entries of other categories', () => {
    const entries = [
      entry(1, [{ field_id: 10, value: '2' }]),
      entry(2, [{ field_id: 10, value: '100' }]),
    ];
    expect(numberFieldSum(entries, 1, 10)).toBe(2);
  });

  it('skips values that are not finite numbers', () => {
    const entries = [
      entry(1, [{ field_id: 10, value: 'oops' }]),
      entry(1, [{ field_id: 10, value: '' }]),
      entry(1, [{ field_id: 10, value: '4' }]),
    ];
    expect(numberFieldSum(entries, 1, 10)).toBe(4);
  });

  it('is zero when the field never appears', () => {
    expect(numberFieldSum([entry(1, [{ field_id: 99, value: '7' }])], 1, 10)).toBe(0);
  });
});

describe('todayEntryForCategory', () => {
  /** A saved (positive id) or optimistic (negative id) entry of `categoryId`. */
  function withId(id: number, categoryId: number): Entry {
    return { ...entry(categoryId, []), id };
  }

  it('finds nothing when the category has not been logged today', () => {
    expect(todayEntryForCategory([withId(5, 2)], 1)).toBeUndefined();
  });

  it('returns the category own entry', () => {
    expect(todayEntryForCategory([withId(5, 2), withId(6, 1)], 1)?.id).toBe(6);
  });

  it('keeps landing on the same record when the day has several', () => {
    // Otherwise a second tap would open a different entry than the first, and
    // the day would end as a pile of half-filled records.
    const entries = [withId(9, 1), withId(4, 1), withId(7, 1)];
    expect(todayEntryForCategory(entries, 1)?.id).toBe(4);
  });

  it('ignores optimistic entries, which the server has never heard of', () => {
    // A negative id is this session own placeholder; editing it would PUT to an
    // id the backend never issued.
    expect(todayEntryForCategory([withId(-1, 1)], 1)).toBeUndefined();
    expect(todayEntryForCategory([withId(-1, 1), withId(8, 1)], 1)?.id).toBe(8);
  });
});

describe('buildCheckedMap', () => {
  const checklist = category({
    id: 5,
    display_mode: 'checklist',
    fields: [
      field({ id: 50, field_type: 'boolean', order: 0 }),
      field({ id: 51, field_type: 'boolean', order: 1 }),
      field({ id: 52, field_type: 'text', order: 2 }),
    ],
  });

  it('marks only the fields stored as "true"', () => {
    const map = buildCheckedMap([checklist], [entry(5, [{ field_id: 50, value: 'true' }])]);
    expect(map[5]).toEqual({ 50: true, 51: false });
  });

  it('leaves every field unchecked when there is no entry yet', () => {
    expect(buildCheckedMap([checklist], [])[5]).toEqual({ 50: false, 51: false });
  });

  it('skips categories that are not checklists', () => {
    const form = category({ id: 6, display_mode: 'form' });
    expect(buildCheckedMap([form], [])).toEqual({});
  });
});

describe('setFieldChecked / isFieldChecked', () => {
  const initial: CheckedMap = { 5: { 50: false, 51: true } };

  it('reads an unknown category as unchecked', () => {
    expect(isFieldChecked({}, 5, 50)).toBe(false);
  });

  it('flips one field without touching its siblings', () => {
    const next = setFieldChecked(initial, 5, 50, true);
    expect(isFieldChecked(next, 5, 50)).toBe(true);
    expect(isFieldChecked(next, 5, 51)).toBe(true);
  });

  it('does not mutate the previous state', () => {
    setFieldChecked(initial, 5, 50, true);
    expect(initial[5][50]).toBe(false);
  });

  it('restores the exact previous state when the optimistic flip is rolled back', () => {
    const current = isFieldChecked(initial, 5, 50);
    const optimistic = setFieldChecked(initial, 5, 50, !current);
    const rolledBack = setFieldChecked(optimistic, 5, 50, current);
    expect(rolledBack).toEqual(initial);
  });

  it('creates the category bucket when the field is new', () => {
    expect(setFieldChecked({}, 7, 70, true)).toEqual({ 7: { 70: true } });
  });
});

describe('loadStreakMap', () => {
  it('keys the loaded streaks by category id', async () => {
    const map = await loadStreakMap([1, 2], async (id) => streak(id));
    expect(map[1]?.category_id).toBe(1);
    expect(map[2]?.category_id).toBe(2);
  });

  it('degrades a failing category to null and keeps the others', async () => {
    const map = await loadStreakMap([1, 2], async (id) => {
      if (id === 1) throw new Error('boom');
      return streak(id);
    });
    expect(map[1]).toBeNull();
    expect(map[2]?.current_streak).toBe(3);
  });

  it('is an empty map when there are no avoid categories', async () => {
    expect(await loadStreakMap([], async (id) => streak(id))).toEqual({});
  });
});
