'use client';
// [review:need-review] PHASE-01/40-mobile-shell-toggle-manifest-today
// summary: Today-screen state extracted from app/today/page.tsx so desktop and /m/today render the same data and handlers

import { useCallback, useEffect, useState } from 'react';
import { categoriesAPI, entriesAPI, type Category, type Entry } from '@/lib/api';
import { todayISO } from '@/lib/date';
import { partitionTodayCategories, type TodayGroups } from '@/lib/today-categories';
import {
  buildCheckedMap,
  isFieldChecked,
  loadStreakMap,
  setFieldChecked,
  type CheckedMap,
  type StreakMap,
} from '@/lib/today-entries';

/** Everything a Today screen needs; the two shells differ only in markup. */
export interface UseTodayResult {
  date: string;
  entries: Entry[];
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
  /** Re-fetch one avoid category's streak, e.g. after a relapse was logged. */
  reloadStreak: (categoryId: number) => Promise<void>;
}

export function useToday(): UseTodayResult {
  const [categories, setCategories] = useState<Category[]>([]);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [checked, setChecked] = useState<CheckedMap>({});
  const [streaks, setStreaks] = useState<StreakMap>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    try {
      setLoading(true);
      const date = todayISO();
      const [categoriesData, entriesData] = await Promise.all([
        categoriesAPI.getAll(),
        entriesAPI.getAll({ startDate: date, endDate: date }),
      ]);
      setCategories(categoriesData);
      setEntries(entriesData);
      setChecked(buildCheckedMap(categoriesData, entriesData));

      const avoidIds = partitionTodayCategories(categoriesData).avoid.map(
        ({ category }) => category.id
      );
      setStreaks(await loadStreakMap(avoidIds, (id) => categoriesAPI.getStreak(id)));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load today data');
    } finally {
      setLoading(false);
    }
  }, []);

  const reloadStreak = useCallback(async (categoryId: number) => {
    const streak = await categoriesAPI.getStreak(categoryId).catch(() => null);
    setStreaks((prev) => ({ ...prev, [categoryId]: streak }));
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

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

  const groups = partitionTodayCategories(categories);
  const nothingToTrack =
    groups.avoid.length === 0 && groups.checklist.length === 0 && groups.quickForm.length === 0;

  return {
    date: todayISO(),
    entries,
    groups,
    checked,
    streaks,
    loading,
    error,
    nothingToTrack,
    setError,
    toggleField,
    reloadStreak,
  };
}
