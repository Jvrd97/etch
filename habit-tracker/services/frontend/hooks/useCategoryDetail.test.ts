// [review:need-review] PHASE-01/42-mobile-categories-and-detail
// summary: tests for useCategoryDetail — batched load, entry grouping, sibling pager, invalid id guard, streak degrading on its own, and reload after a mutation

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import type { Category, CategoryStreak, Entry, TableDay } from '@/lib/api';

const TIMESTAMP = '2026-07-24T00:00:00Z';

const CATEGORY: Category = {
  id: 1,
  name: 'Sleep',
  display_mode: 'form',
  streak_mode: 'build',
  is_active: true,
  created_at: TIMESTAMP,
  updated_at: TIMESTAMP,
  fields: [],
};

const OTHER_CATEGORY: Category = { ...CATEGORY, id: 2, name: 'Mood' };
const THIRD_CATEGORY: Category = { ...CATEGORY, id: 3, name: 'Reading' };

const DAYS: TableDay[] = [];

const STREAK: CategoryStreak = {
  category_id: 1,
  streak_mode: 'build',
  current_streak: 3,
  best_streak: 9,
  last_relapse_date: null,
};

function entry(id: number, date: string): Entry {
  return {
    id,
    category_id: 1,
    entry_date: date,
    created_at: TIMESTAMP,
    updated_at: TIMESTAMP,
    values: [],
  };
}

const TODAY_ENTRY = entry(10, '2026-07-24');
const SAME_DAY_ENTRY = entry(11, '2026-07-24');
const YESTERDAY_ENTRY = entry(12, '2026-07-23');

let getCategory: ReturnType<typeof mock>;
let getAllCategories: ReturnType<typeof mock>;
let getStreak: ReturnType<typeof mock>;
let getTable: ReturnType<typeof mock>;
let getAllEntries: ReturnType<typeof mock>;

// Declares the whole surface on purpose: bun fixes a module's export *names* the
// first time anything links against it and shares that registry across the run,
// so a partial mock here would delete members other suites reach for.
mock.module('@/lib/api', () => ({
  // The Today screen carries the challenge block (#127). Present in every api
  // mock for the same reason the rest of the surface is: bun fixes a module's
  // export names on first link, so a mock that omits it deletes it for whoever
  // runs next.
  challengesAPI: {
    list: () => Promise.resolve([]),
    get: () => Promise.resolve(null),
    create: () => Promise.resolve(null),
    patch: () => Promise.resolve(null),
    recompute: () => Promise.resolve(null),
  },
  // The day screen's client (#86). Present in every api mock for the same
  // reason the rest of the surface is: bun fixes a module's export names on
  // first link, so a mock that omits it deletes it for whoever runs next.
  dayAPI: {
    getToday: () => Promise.resolve(null),
    get: () => Promise.resolve(null),
  },
  dailySummaryAPI: {
    draft: () => Promise.resolve({ metrics: [], unresolved: [] }),
    apply: () => Promise.resolve({ entry_ids: [] }),
  },
  onboardingAPI: { draft: () => Promise.resolve({ operations: [] }) },
  insightsAPI: {
    getAll: () => Promise.resolve([]),
    getById: () => Promise.resolve(null),
    create: () => Promise.resolve(null),
  },
  categoriesAPI: {
    getById: (id: number) => getCategory(id),
    getAll: (activeOnly?: boolean) => getAllCategories(activeOnly),
    getStreak: (id: number) => getStreak(id),
    create: () => Promise.resolve(CATEGORY),
    update: () => Promise.resolve(CATEGORY),
    delete: () => Promise.resolve(undefined),
  },
  entriesAPI: {
    getAll: (params?: unknown) => getAllEntries(params),
    create: () => Promise.resolve(null),
    update: () => Promise.resolve(null),
    delete: () => Promise.resolve(undefined),
    upsertChecklist: () => Promise.resolve({}),
  },
  journalAPI: {
    getAll: () => Promise.resolve({ items: [], total: 0 }),
    getById: () => Promise.resolve(null),
    create: () => Promise.resolve(null),
  },
  tableAPI: { get: (from: string, to: string) => getTable(from, to) },
}));

const { useCategoryDetail } = await import('./useCategoryDetail');

beforeEach(() => {
  getCategory = mock(() => Promise.resolve(CATEGORY));
  getAllCategories = mock(() =>
    Promise.resolve([CATEGORY, OTHER_CATEGORY, THIRD_CATEGORY])
  );
  getStreak = mock(() => Promise.resolve(STREAK));
  getTable = mock(() => Promise.resolve({ days: DAYS }));
  getAllEntries = mock(() =>
    Promise.resolve([TODAY_ENTRY, SAME_DAY_ENTRY, YESTERDAY_ENTRY])
  );
});

afterEach(() => {
  cleanup();
});

describe('useCategoryDetail', () => {
  it('loads the category, its siblings, the chart days and the entries', async () => {
    const { result } = renderHook(() => useCategoryDetail(1));

    await waitFor(() => expect(result.current.loaded).toBe(true));

    expect(result.current.category).toEqual(CATEGORY);
    expect(result.current.categories).toHaveLength(3);
    expect(result.current.days).toEqual(DAYS);
    expect(result.current.entries).toHaveLength(3);
    expect(result.current.streak).toEqual(STREAK);
    expect(getCategory).toHaveBeenCalledWith(1);
  });

  it('groups the entries by date for rendering', async () => {
    const { result } = renderHook(() => useCategoryDetail(1));
    await waitFor(() => expect(result.current.loaded).toBe(true));

    expect(result.current.entryGroups).toEqual([
      ['2026-07-24', [TODAY_ENTRY, SAME_DAY_ENTRY]],
      ['2026-07-23', [YESTERDAY_ENTRY]],
    ]);
  });

  it('asks for the unfiltered sibling list the list screens link from', async () => {
    const { result } = renderHook(() => useCategoryDetail(1));
    await waitFor(() => expect(result.current.loaded).toBe(true));

    // active-only would drop an inactive category out of its own tab strip and
    // leave the pager pointing nowhere.
    expect(getAllCategories).toHaveBeenCalledWith(false);
  });

  it('resolves the neighbours the pager links to', async () => {
    const { result } = renderHook(() => useCategoryDetail(2));
    await waitFor(() => expect(result.current.loaded).toBe(true));

    expect(result.current.prev).toEqual(CATEGORY);
    expect(result.current.next).toEqual(THIRD_CATEGORY);
  });

  it('degrades to no streak block instead of blanking the page', async () => {
    getStreak = mock(() => Promise.reject(new Error('streak service down')));
    const { result } = renderHook(() => useCategoryDetail(1));

    await waitFor(() => expect(result.current.loaded).toBe(true));
    // A secondary widget failing must not take the chart and the history with it.
    expect(result.current.streak).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it('refuses a non-numeric id without firing a request', async () => {
    const { result } = renderHook(() => useCategoryDetail(Number('abc')));

    expect(result.current.invalidId).toBe(true);
    expect(result.current.loaded).toBe(false);
    expect(getCategory).not.toHaveBeenCalled();
  });

  it('surfaces a load failure and lets the screen dismiss it', async () => {
    getCategory = mock(() => Promise.reject(new Error('not found')));
    const { result } = renderHook(() => useCategoryDetail(1));

    await waitFor(() => expect(result.current.error).toBe('not found'));

    act(() => {
      result.current.setError(null);
    });
    expect(result.current.error).toBeNull();
  });

  it('refetches after an entry was created or deleted', async () => {
    const { result } = renderHook(() => useCategoryDetail(1));
    await waitFor(() => expect(result.current.loaded).toBe(true));

    getAllEntries = mock(() => Promise.resolve([TODAY_ENTRY]));
    act(() => {
      result.current.reload();
    });

    await waitFor(() => expect(result.current.entries).toEqual([TODAY_ENTRY]));
  });

  it('clears a stale load error once the next load succeeds', async () => {
    getCategory = mock(() => Promise.reject(new Error('not found')));
    const { result } = renderHook(() => useCategoryDetail(1));
    await waitFor(() => expect(result.current.error).toBe('not found'));

    getCategory = mock(() => Promise.resolve(CATEGORY));
    act(() => {
      result.current.reload();
    });

    // Navigating the category strip re-runs the load; a banner from a one-off
    // failure must not follow the user onto the category that loaded fine.
    await waitFor(() => expect(result.current.loaded).toBe(true));
    expect(result.current.error).toBeNull();
  });
});
