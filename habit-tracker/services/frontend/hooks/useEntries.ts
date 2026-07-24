'use client';
// [review:need-review] PHASE-01/41-mobile-entries-fullscreen-sheet
// summary: Entries-screen state extracted from app/entries/page.tsx so the desktop page and /m/entries render the same data, filter, visibility refresh and reload behaviour; a successful load retires only the load error, never one the screen reported

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useRefreshOnVisible } from '@/hooks/useRefreshOnVisible';
import { categoriesAPI, entriesAPI, type Category, type Entry } from '@/lib/api';
import { groupEntriesByDate } from '@/lib/entry-groups';

/** How many entries one screenful of the list asks for. */
const ENTRY_PAGE_SIZE = 50;

/**
 * The banner message plus where it came from.
 *
 * The origin matters because a successful load may only retire a *load*
 * failure. A message the screen pushed in — a rejected delete, say — describes
 * something the refetch knows nothing about and has to survive it.
 */
interface EntriesError {
  message: string;
  fromLoad: boolean;
}

/** Everything an Entries screen needs; the two shells differ only in markup. */
export interface UseEntriesResult {
  entries: Entry[];
  categories: Category[];
  /** Entries bucketed by `entry_date`, in first-seen order — the list's render shape. */
  grouped: Array<[string, Entry[]]>;
  loading: boolean;
  error: string | null;
  /** Category the list is narrowed to, or null for "all categories". */
  filterCategory: number | null;
  setFilterCategory: (categoryId: number | null) => void;
  setError: (message: string | null) => void;
  /** Re-fetch the list, e.g. after an entry was created, edited or deleted. */
  reload: () => Promise<void>;
  /** The category an entry belongs to, or undefined when it was deleted meanwhile. */
  categoryOf: (entry: Entry) => Category | undefined;
}

export function useEntries(): UseEntriesResult {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [errorState, setErrorState] = useState<EntriesError | null>(null);
  const [filterCategory, setFilterCategory] = useState<number | null>(null);

  const setError = useCallback((message: string | null) => {
    setErrorState(message === null ? null : { message, fromLoad: false });
  }, []);

  /**
   * Fetch the list for the current filter.
   *
   * `showSpinner` separates the first load — nothing on screen yet, so a
   * spinner is the honest state — from a reload after a mutation, where the
   * previous list stays rendered until the new one lands. Flipping `loading`
   * there would blank a screen the user is looking at and, on mobile, collapse
   * the list under the editor sheet that just closed.
   */
  const loadData = useCallback(
    async ({ showSpinner = false } = {}) => {
      try {
        if (showSpinner) setLoading(true);
        const [entriesData, categoriesData] = await Promise.all([
          entriesAPI.getAll({
            categoryId: filterCategory ?? undefined,
            limit: ENTRY_PAGE_SIZE,
          }),
          categoriesAPI.getAll(),
        ]);
        setEntries(entriesData);
        setCategories(categoriesData);
        // A reload that succeeds must retire the previous *load* failure, or the
        // error banner outlives the outage that caused it. Anything the screen
        // reported stays: the silent refresh on `visibilitychange` fires exactly
        // when the user comes back to read it.
        setErrorState((previous) => (previous?.fromLoad ? null : previous));
      } catch (err) {
        setErrorState({
          message: err instanceof Error ? err.message : 'Failed to load entries',
          fromLoad: true,
        });
      } finally {
        setLoading(false);
      }
    },
    [filterCategory]
  );

  useEffect(() => {
    loadData({ showSpinner: true });
  }, [loadData]);

  const reload = useCallback(async () => {
    await loadData();
  }, [loadData]);

  const refresh = useCallback(() => {
    void loadData();
  }, [loadData]);

  // Standalone PWA never reloads the document, so returning to /m/entries would
  // otherwise keep rendering the list fetched when the app was launched — an
  // entry logged on /today would be missing here.
  useRefreshOnVisible(refresh);

  const categoryOf = useCallback(
    (entry: Entry) => categories.find((category) => category.id === entry.category_id),
    [categories]
  );

  // Memoised, so the hook's public contract does not hand out a new array on
  // every render and invalidate whatever the screens memoise off it.
  const grouped = useMemo(() => groupEntriesByDate(entries), [entries]);

  return {
    entries,
    categories,
    grouped,
    loading,
    error: errorState?.message ?? null,
    filterCategory,
    setFilterCategory,
    setError,
    reload,
    categoryOf,
  };
}
