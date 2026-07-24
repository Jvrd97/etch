// [review:need-review] PHASE-01/40-mobile-shell-toggle-manifest-today
// summary: pure Today-screen entry state — number totals, checklist map with optimistic flip/rollback, streak loading that degrades to null

import type { Category, CategoryStreak, Entry } from './api';
import { booleanFields } from './today-categories';

/** The string the API stores for a checked boolean field. */
const TRUE_VALUE = 'true';

/** checked-state per category: category_id -> field_id -> boolean */
export type CheckedMap = Record<number, Record<number, boolean>>;

/** current/best streak per avoid category; null while loading or on failure. */
export type StreakMap = Record<number, CategoryStreak | null>;

/** Sum of today's values for one number field across all of a category's entries. */
export function numberFieldSum(
  entries: Entry[],
  categoryId: number,
  fieldId: number
): number {
  return entries
    .filter((entry) => entry.category_id === categoryId)
    .reduce((sum, entry) => {
      const value = entry.values.find((v) => v.field_id === fieldId);
      const parsed = value ? Number(value.value) : Number.NaN;
      return Number.isFinite(parsed) ? sum + parsed : sum;
    }, 0);
}

/** Checked-state for every boolean field of every checklist category. */
export function buildCheckedMap(categories: Category[], entries: Entry[]): CheckedMap {
  const map: CheckedMap = {};
  for (const category of categories) {
    if (category.display_mode !== 'checklist') continue;
    const entry = entries.find((e) => e.category_id === category.id);
    const fieldsChecked: Record<number, boolean> = {};
    for (const field of booleanFields(category)) {
      const value = entry?.values.find((v) => v.field_id === field.id);
      fieldsChecked[field.id] = value?.value === TRUE_VALUE;
    }
    map[category.id] = fieldsChecked;
  }
  return map;
}

/** Current state of one checkbox; unknown categories and fields read as unchecked. */
export function isFieldChecked(
  map: CheckedMap,
  categoryId: number,
  fieldId: number
): boolean {
  return map[categoryId]?.[fieldId] ?? false;
}

/**
 * A copy of `map` with one field set. Used both for the optimistic flip and for
 * the rollback, so a failed save restores exactly the previous value and leaves
 * every sibling field untouched.
 */
export function setFieldChecked(
  map: CheckedMap,
  categoryId: number,
  fieldId: number,
  value: boolean
): CheckedMap {
  return {
    ...map,
    [categoryId]: { ...map[categoryId], [fieldId]: value },
  };
}

/**
 * Streaks for the given avoid categories. They are a secondary widget: a failed
 * fetch degrades that one card to `null` (rendered as "—") instead of failing
 * the whole screen.
 */
export async function loadStreakMap(
  categoryIds: readonly number[],
  fetchStreak: (categoryId: number) => Promise<CategoryStreak>
): Promise<StreakMap> {
  const loaded = await Promise.all(
    categoryIds.map(
      async (id) => [id, await fetchStreak(id).catch(() => null)] as const
    )
  );
  return Object.fromEntries(loaded);
}
