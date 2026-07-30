// [review:need-review] PHASE-01/61-today-total-owned-by-hook
// summary: pure Today-screen entry state — number totals, optimistic number entries merged over the fetched snapshot, checklist map with flip/rollback, streak loading that degrades to null

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

/**
 * A single number entry as it will look once saved, built before the request is
 * sent so the total moves on tap.
 *
 * `id` is caller-supplied and negative for an unsaved entry: it keeps the shape
 * a real `Entry` has — the totals and the merge only ever key on ids — while
 * staying outside the range the server hands out, so a refetch can never
 * mistake it for a row it returned.
 */
export function optimisticNumberEntry(args: {
  id: number;
  categoryId: number;
  fieldId: number;
  entryDate: string;
  amount: number;
}): Entry {
  const { id, categoryId, fieldId, entryDate, amount } = args;
  const now = new Date().toISOString();
  return {
    id,
    category_id: categoryId,
    entry_date: entryDate,
    created_at: now,
    updated_at: now,
    values: [{ id, entry_id: id, field_id: fieldId, value: String(amount) }],
  };
}

/**
 * The fetched snapshot plus the entries that are not in it yet.
 *
 * Dedupe is by id, which is what makes the refetch race harmless: a snapshot
 * fetched before the POST was visible simply lacks the row, so the local copy
 * keeps the total honest, and the first snapshot that does contain it drops the
 * duplicate instead of counting the increment twice.
 */
export function mergeOptimisticEntries(fetched: Entry[], optimistic: Entry[]): Entry[] {
  if (optimistic.length === 0) return fetched;
  const known = new Set(fetched.map((entry) => entry.id));
  return [...fetched, ...optimistic.filter((entry) => !known.has(entry.id))];
}

/**
 * Today's entry for a category, for the editor a card tap opens.
 *
 * The oldest saved entry wins, so repeated taps keep landing on the same record
 * instead of scattering the day across several. Optimistic entries are skipped
 * by their negative id: they have no row on the server yet, and editing one
 * would `PUT` to an id the backend has never issued.
 */
export function todayEntryForCategory(
  entries: Entry[],
  categoryId: number
): Entry | undefined {
  return entries
    .filter((entry) => entry.category_id === categoryId && entry.id > 0)
    .reduce<Entry | undefined>(
      (oldest, entry) => (oldest === undefined || entry.id < oldest.id ? entry : oldest),
      undefined
    );
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
