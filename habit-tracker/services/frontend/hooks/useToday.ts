'use client';
// [review:need-review] PHASE-01/61-today-total-owned-by-hook
// summary: Today-screen state for both shells — snapshot fetching plus the optimistic checklist flip and number increment, each rolled back on its own failure

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRefreshOnVisible } from '@/hooks/useRefreshOnVisible';
import { categoriesAPI, entriesAPI, type Category, type Entry } from '@/lib/api';
import { todayISO } from '@/lib/date';
import { partitionTodayCategories, type TodayGroups } from '@/lib/today-categories';
import {
  buildCheckedMap,
  isFieldChecked,
  loadStreakMap,
  mergeOptimisticEntries,
  optimisticNumberEntry,
  setFieldChecked,
  type CheckedMap,
  type StreakMap,
} from '@/lib/today-entries';

/** Everything a Today screen needs; the two shells differ only in markup. */
export interface UseTodayResult {
  date: string;
  entries: Entry[];
  /**
   * Every active category, ungrouped.
   *
   * `groups` routes categories to widgets; the challenge form needs the plain
   * list, because a rule may point at a category no Today widget shows.
   */
  categories: Category[];
  groups: TodayGroups;
  checked: CheckedMap;
  streaks: StreakMap;
  loading: boolean;
  error: string | null;
  /** True when no category routes to any Today widget. */
  nothingToTrack: boolean;
  setError: (message: string | null) => void;
  /** Optimistically flip a checklist field, rolling back if the save fails. */
  toggleField: (categoryId: number, fieldId: number) => Promise<void>;
  /**
   * Log one number entry, showing it in `entries` before the request resolves
   * and withdrawing exactly that increment if the request fails. Resolves false
   * on failure, so the caller can keep whatever it would have to retype.
   */
  addNumber: (categoryId: number, fieldId: number, amount: number) => Promise<boolean>;
  /** Re-fetch one avoid category's streak, e.g. after a relapse was logged. */
  reloadStreak: (categoryId: number) => Promise<void>;
  /**
   * Re-fetch the whole snapshot without blanking the screen — what a full entry
   * editor calls once it has saved, since its edit can touch any field.
   */
  reload: () => Promise<void>;
}

export function useToday(): UseTodayResult {
  const [categories, setCategories] = useState<Category[]>([]);
  const [entries, setEntries] = useState<Entry[]>([]);
  // Entries this session logged that the last snapshot did not (yet) contain:
  // in flight, or saved after the snapshot was taken. Kept apart from `entries`
  // so a refetch can replace the snapshot without discarding them.
  const [optimisticEntries, setOptimisticEntries] = useState<Entry[]>([]);
  const nextOptimisticId = useRef(-1);
  const [checked, setChecked] = useState<CheckedMap>({});
  const [streaks, setStreaks] = useState<StreakMap>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  /**
   * Fetch the whole Today snapshot.
   *
   * `showSpinner` is the difference between the first load (nothing on screen
   * yet, so a spinner is the honest state) and a background refetch triggered
   * by the tab becoming visible again: there the old snapshot stays rendered
   * until the new one lands, so flipping `loading` would blank a screen the
   * user is already looking at.
   */
  const loadData = useCallback(async ({ showSpinner = false } = {}) => {
    try {
      if (showSpinner) setLoading(true);
      const date = todayISO();
      const [categoriesData, entriesData] = await Promise.all([
        categoriesAPI.getAll(),
        entriesAPI.getAll({ startDate: date, endDate: date }),
      ]);
      setCategories(categoriesData);
      setEntries(entriesData);
      // Whatever the snapshot now carries is no longer ours to hold; dropping it
      // here is what keeps a saved increment from being counted twice.
      const fetchedIds = new Set(entriesData.map((entry) => entry.id));
      setOptimisticEntries((prev) => prev.filter((entry) => !fetchedIds.has(entry.id)));
      setChecked(buildCheckedMap(categoriesData, entriesData));

      const avoidIds = partitionTodayCategories(categoriesData).avoid.map(
        ({ category }) => category.id
      );
      setStreaks(await loadStreakMap(avoidIds, (id) => categoriesAPI.getStreak(id)));
      // A silent refetch that succeeds must retire the previous failure, or the
      // error banner outlives the outage that caused it.
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load today data');
    } finally {
      setLoading(false);
    }
  }, []);

  const reload = useCallback(async () => {
    await loadData();
  }, [loadData]);

  const reloadStreak = useCallback(async (categoryId: number) => {
    const streak = await categoriesAPI.getStreak(categoryId).catch(() => null);
    setStreaks((prev) => ({ ...prev, [categoryId]: streak }));
  }, []);

  useEffect(() => {
    loadData({ showSpinner: true });
  }, [loadData]);

  const refresh = useCallback(() => {
    void loadData();
  }, [loadData]);

  // Standalone PWA never reloads the document, so /m/today would otherwise keep
  // rendering the snapshot fetched when the app was launched.
  useRefreshOnVisible(refresh);

  const toggleField = useCallback(
    async (categoryId: number, fieldId: number) => {
      const current = isFieldChecked(checked, categoryId, fieldId);
      const next = !current;

      setChecked((prev) => setFieldChecked(prev, categoryId, fieldId, next));

      try {
        await entriesAPI.upsertChecklist({
          category_id: categoryId,
          entry_date: todayISO(),
          values: { [fieldId]: next },
        });
      } catch (err) {
        setChecked((prev) => setFieldChecked(prev, categoryId, fieldId, current));
        setError(err instanceof Error ? err.message : 'Failed to save check');
      }
    },
    [checked]
  );

  /**
   * One tap, one entry, no in-flight lock: five taps are five increments, and a
   * failure among them withdraws only its own — the rest stay banked.
   */
  const addNumber = useCallback(
    async (categoryId: number, fieldId: number, amount: number): Promise<boolean> => {
      const localId = nextOptimisticId.current;
      nextOptimisticId.current -= 1;
      const entryDate = todayISO();

      setOptimisticEntries((prev) => [
        ...prev,
        optimisticNumberEntry({ id: localId, categoryId, fieldId, entryDate, amount }),
      ]);

      try {
        const saved = await entriesAPI.create({
          category_id: categoryId,
          entry_date: entryDate,
          values: [{ field_id: fieldId, value: String(amount) }],
        });
        // Adopt the server id so the snapshot that first returns this row
        // reclaims it. The local values are kept as they are: the increment on
        // screen must not shift because the response spelled it differently.
        setOptimisticEntries((prev) =>
          prev.map((entry) => (entry.id === localId ? { ...entry, id: saved.id } : entry))
        );
        return true;
      } catch (err) {
        setOptimisticEntries((prev) => prev.filter((entry) => entry.id !== localId));
        setError(err instanceof Error ? err.message : 'Failed to save entry');
        return false;
      }
    },
    []
  );

  const groups = partitionTodayCategories(categories);
  const nothingToTrack =
    groups.avoid.length === 0 && groups.checklist.length === 0 && groups.quickForm.length === 0;

  return {
    date: todayISO(),
    entries: mergeOptimisticEntries(entries, optimisticEntries),
    categories,
    groups,
    checked,
    streaks,
    loading,
    error,
    nothingToTrack,
    setError,
    toggleField,
    addNumber,
    reloadStreak,
    reload,
  };
}
