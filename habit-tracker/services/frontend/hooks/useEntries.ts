'use client';
// [review:need-review] PHASE-01/41-mobile-entries-fullscreen-sheet, #76, #311
// summary: Entries state loads tracker entries and, without a category filter, journal notes into one feed ordered by the day they belong to; shares filtering, visibility refresh and reload across shells
// summary: #311 — the category list comes through the shared read cache (`readCategories`): the readers of one moment share one request

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useRefreshOnVisible } from '@/hooks/useRefreshOnVisible';
import {
  entriesAPI,
  journalAPI,
  type Category,
  type Entry,
  type JournalEntry,
} from '@/lib/api';
import { readCategories } from '@/lib/categories-cache';
import { mergeActivityFeed, type ActivityFeedItem } from '@/lib/activity-feed';

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
  /**
   * Tracker entries and journal notes as one feed. Journal notes belong to no
   * category, so they are left out while a category filter is on.
   */
  activityItems: ActivityFeedItem[];
  categories: Category[];
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
  const [journals, setJournals] = useState<JournalEntry[]>([]);
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
        // Both sources come back newest day first (the backend default), so one
        // page covers the most recent days of the history rather than the most
        // recently typed records.
        const [entriesData, journalData, categoriesData] = await Promise.all([
          entriesAPI.getAll({
            categoryId: filterCategory ?? undefined,
            limit: ENTRY_PAGE_SIZE,
          }),
          filterCategory === null
            ? journalAPI.getAll({ limit: ENTRY_PAGE_SIZE }).then(({ items }) => items)
            : Promise.resolve<JournalEntry[]>([]),
          readCategories(),
        ]);
        setEntries(entriesData);
        setJournals(journalData);
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
  const activityItems = useMemo(
    () => mergeActivityFeed(entries, journals),
    [entries, journals]
  );

  return {
    activityItems,
    categories,
    loading,
    error: errorState?.message ?? null,
    filterCategory,
    setFilterCategory,
    setError,
    reload,
    categoryOf,
  };
}
