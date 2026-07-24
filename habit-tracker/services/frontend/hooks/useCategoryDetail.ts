'use client';
// [review:need-review] PHASE-01/42-mobile-categories-and-detail
// summary: category-detail state extracted from app/categories/[id]/page.tsx — one batched load of category, siblings, chart days, entries and streak, so the desktop page and /m/categories/[id] render the same screen

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  categoriesAPI,
  entriesAPI,
  tableAPI,
  type Category,
  type CategoryStreak,
  type Entry,
  type TableDay,
} from '@/lib/api';
import { categorySiblings } from '@/lib/category-nav';
import { chartDateRange } from '@/lib/chart-data';
import { groupEntriesByDate } from '@/lib/entry-groups';

/** Full history without pagination (ticket #22: pagination is out of scope). */
const ENTRIES_FETCH_LIMIT = 1000;

export const LOAD_CATEGORY_ERROR = 'Failed to load category';

/** The parts of the screen's state that do not depend on the load having finished. */
interface CategoryDetailCommon {
  /** Every category, for the pager and the tab strip. */
  categories: Category[];
  /** Streak summary, or null when the category tracks none — or the call failed. */
  streak: CategoryStreak | null;
  /** Entries bucketed by `entry_date`, in first-seen order — the history's render shape. */
  entryGroups: Array<[string, Entry[]]>;
  /** True when the route carries something that is not a category id. */
  invalidId: boolean;
  error: string | null;
  setError: (message: string | null) => void;
  /** Re-run the batched load, e.g. after an entry was created, edited or deleted. */
  reload: () => void;
  /** Previous category in list order, or null at the start of the list. */
  prev: Category | null;
  /** Next category in list order, or null at the end of the list. */
  next: Category | null;
}

/** The batch has landed: the chart and the history can be rendered as they are. */
interface CategoryDetailLoaded extends CategoryDetailCommon {
  loaded: true;
  category: Category;
  days: TableDay[];
  entries: Entry[];
}

/** Still loading, already failed, or pointed at an invalid id. */
interface CategoryDetailPending extends CategoryDetailCommon {
  loaded: false;
  category: Category | null;
  days: TableDay[] | null;
  entries: Entry[] | null;
}

/**
 * Everything a category detail screen needs; the two shells differ only in markup.
 *
 * A discriminated union rather than three independent nullables: the screens
 * check `loaded` once and get the data non-null from there on, instead of
 * repeating a null check per field to convince the compiler.
 */
export type UseCategoryDetailResult = CategoryDetailLoaded | CategoryDetailPending;

export function useCategoryDetail(categoryId: number): UseCategoryDetailResult {
  const invalidId = !Number.isInteger(categoryId) || categoryId <= 0;

  const [category, setCategory] = useState<Category | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [days, setDays] = useState<TableDay[] | null>(null);
  const [entries, setEntries] = useState<Entry[] | null>(null);
  const [streak, setStreak] = useState<CategoryStreak | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshCounter, setRefreshCounter] = useState(0);

  useEffect(() => {
    if (invalidId) return;
    // The screen may unmount (or be pointed at another category) while the batch
    // is in flight; without this its result would overwrite the newer one.
    let cancelled = false;

    const load = async () => {
      try {
        // Cleared up front rather than on success only: the effect re-runs on
        // every hop along the category strip, and a banner from a one-off
        // failure must not follow the user onto the category that loaded fine.
        setError(null);
        const { from, to } = chartDateRange(new Date());
        const [categoryResult, categoriesResult, tableResult, entriesResult, streakResult] =
          await Promise.all([
            categoriesAPI.getById(categoryId),
            // Unfiltered, matching the list screens that link here: with the
            // active-only default an inactive category opened from
            // /m/categories finds itself missing from its own tab strip and
            // gets a dead prev/next pager.
            categoriesAPI.getAll(false),
            tableAPI.get(from, to),
            entriesAPI.getAll({ categoryId, limit: ENTRIES_FETCH_LIMIT }),
            // Secondary widget: a failure here must not blank the whole page,
            // so it degrades to "no streak block" instead of rejecting the batch.
            categoriesAPI.getStreak(categoryId).catch(() => null),
          ]);
        if (cancelled) return;
        setCategory(categoryResult);
        setCategories(categoriesResult);
        setDays(tableResult.days);
        setEntries(entriesResult);
        setStreak(streakResult);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : LOAD_CATEGORY_ERROR);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [categoryId, invalidId, refreshCounter]);

  const reload = useCallback(() => {
    setRefreshCounter((n) => n + 1);
  }, []);

  // Memoised, so the hook's public contract does not hand out a new array on
  // every render and invalidate whatever the screens memoise off it.
  const entryGroups = useMemo(
    () => (entries === null ? [] : groupEntriesByDate(entries)),
    [entries]
  );

  const { prev, next } = useMemo(
    () => categorySiblings(categories, categoryId),
    [categories, categoryId]
  );

  const common: CategoryDetailCommon = {
    categories,
    streak,
    entryGroups,
    invalidId,
    error,
    setError,
    reload,
    prev,
    next,
  };

  // The streak is deliberately not part of it: it degrades on its own, and
  // waiting for it would hold the whole page back on a secondary widget.
  const loaded = category !== null && days !== null && entries !== null;
  if (loaded) return { ...common, loaded: true, category, days, entries };
  return { ...common, loaded: false, category, days, entries };
}
