// [review:need-review] PHASE-01/40-mobile-shell-toggle-manifest-today, PHASE-01/42-mobile-categories-and-detail
// summary: tests for useToday — the visibility refetch must stay silent (no spinner, no data reset)

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import type { Category, Entry } from '@/lib/api';

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

const ENTRY: Entry = {
  id: 10,
  category_id: 1,
  entry_date: '2026-07-24',
  created_at: TIMESTAMP,
  updated_at: TIMESTAMP,
  values: [],
};

/** Resolves only when the test releases it, so a refetch can be observed mid-flight. */
function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

let getAllCategories: ReturnType<typeof mock>;
let getAllEntries: ReturnType<typeof mock>;

// The whole module is replaced process-wide, so the members other suites reach
// for have to stay present even though this one never calls them.
mock.module('@/lib/api', () => ({
  categoriesAPI: {
    getAll: () => getAllCategories(),
    getById: () => Promise.resolve(null),
    getStreak: () => Promise.resolve(null),
    create: () => Promise.resolve(null),
    update: () => Promise.resolve(null),
    delete: () => Promise.resolve(undefined),
  },
  entriesAPI: {
    getAll: () => getAllEntries(),
    create: () => Promise.resolve(null),
    update: () => Promise.resolve(null),
    delete: () => Promise.resolve(undefined),
    upsertChecklist: () => Promise.resolve({}),
  },
  tableAPI: { get: () => Promise.resolve({ days: [] }) },
}));

const { useToday } = await import('./useToday');

beforeEach(() => {
  getAllCategories = mock(() => Promise.resolve([CATEGORY]));
  getAllEntries = mock(() => Promise.resolve([ENTRY]));
});

afterEach(() => {
  cleanup();
});

describe('useToday', () => {
  it('shows the spinner on the initial load', async () => {
    const { result } = renderHook(() => useToday());

    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.entries).toEqual([ENTRY]);
  });

  it('refetches silently when the tab becomes visible again', async () => {
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    const pendingCategories = deferred<Category[]>();
    const pendingEntries = deferred<Entry[]>();
    getAllCategories = mock(() => pendingCategories.promise);
    getAllEntries = mock(() => pendingEntries.promise);

    act(() => {
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await waitFor(() => expect(getAllEntries).toHaveBeenCalled());

    // Mid-flight: no spinner, and the previously loaded data is still rendered.
    expect(result.current.loading).toBe(false);
    expect(result.current.entries).toEqual([ENTRY]);

    await act(async () => {
      pendingCategories.resolve([CATEGORY]);
      pendingEntries.resolve([ENTRY]);
      await Promise.resolve();
    });
    expect(result.current.loading).toBe(false);
  });

  it('clears a stale error once a later fetch succeeds', async () => {
    getAllCategories = mock(() => Promise.reject(new Error('network down')));
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.error).toBe('network down'));

    getAllCategories = mock(() => Promise.resolve([CATEGORY]));
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'));
    });

    await waitFor(() => expect(result.current.error).toBeNull());
  });
});
