// [review:need-review] PHASE-01/61-today-total-owned-by-hook
// summary: tests for useToday — silent visibility refetch, and the optimistic number increment with per-tap rollback

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import type { Category, Entry, Field } from '@/lib/api';
import { numberFieldSum } from '@/lib/today-entries';

const TIMESTAMP = '2026-07-24T00:00:00Z';
const TODAY = '2026-07-24';

const GLASSES_FIELD: Field = {
  id: 7,
  category_id: 1,
  name: 'Glasses',
  field_type: 'number',
  is_required: false,
  order: 1,
  created_at: TIMESTAMP,
  updated_at: TIMESTAMP,
};

const CATEGORY: Category = {
  id: 1,
  name: 'Sleep',
  display_mode: 'form',
  streak_mode: 'build',
  is_active: true,
  created_at: TIMESTAMP,
  updated_at: TIMESTAMP,
  fields: [GLASSES_FIELD],
};

const ENTRY: Entry = {
  id: 10,
  category_id: 1,
  entry_date: TODAY,
  created_at: TIMESTAMP,
  updated_at: TIMESTAMP,
  values: [],
};

/** A saved entry as the API would echo it back. */
function savedEntry(id: number, amount: number): Entry {
  return {
    id,
    category_id: CATEGORY.id,
    entry_date: TODAY,
    created_at: TIMESTAMP,
    updated_at: TIMESTAMP,
    values: [
      { id, entry_id: id, field_id: GLASSES_FIELD.id, value: String(amount) },
    ],
  };
}

/** Today's total for the number field, as the screens compute it. */
function totalOf(entries: Entry[]): number {
  return numberFieldSum(entries, CATEGORY.id, GLASSES_FIELD.id);
}

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
let createEntry: ReturnType<typeof mock>;

// The whole module is replaced process-wide, so the members other suites reach
// for have to stay present even though this one never calls them.
mock.module('@/lib/api', () => ({
  quickMarksAPI: {
    list: () => Promise.resolve([]),
    tap: () => Promise.resolve(null),
  },
  // The chat client (#118). Present in every api mock for the same reason the
  // rest of the surface is: bun fixes a module's export names on first link, so
  // a mock that omits it deletes it for whoever runs next.
  chatAPI: {
    list: () => Promise.resolve([]),
    create: () => Promise.resolve(null),
    get: () => Promise.resolve(null),
    streamMessage: () => Promise.resolve(undefined),
  },
  // The training client (#92). Present in every api mock for the same reason
  // the rest of the surface is: bun fixes a module's export names on first
  // link, so a mock that omits it deletes it for whoever runs next.
  trainingAPI: { getState: () => Promise.resolve(null) },
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
    getAll: () => getAllCategories(),
    getById: () => Promise.resolve(null),
    getStreak: () => Promise.resolve(null),
    create: () => Promise.resolve(null),
    update: () => Promise.resolve(null),
    delete: () => Promise.resolve(undefined),
  },
  entriesAPI: {
    getAll: () => getAllEntries(),
    create: (data: unknown) => createEntry(data),
    update: () => Promise.resolve(null),
    delete: () => Promise.resolve(undefined),
    upsertChecklist: () => Promise.resolve({}),
  },
  journalAPI: {
    getAll: () => Promise.resolve({ items: [], total: 0 }),
    getById: () => Promise.resolve(null),
    create: () => Promise.resolve(null),
  },
  tableAPI: { get: () => Promise.resolve({ days: [] }) },
}));

mock.module('@/lib/date', () => ({ todayISO: () => TODAY }));

const { useToday } = await import('./useToday');

beforeEach(() => {
  getAllCategories = mock(() => Promise.resolve([CATEGORY]));
  getAllEntries = mock(() => Promise.resolve([ENTRY]));
  createEntry = mock(() => Promise.resolve(savedEntry(11, 1)));
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

describe('useToday.addNumber', () => {
  it('shows the increment before the request resolves', async () => {
    createEntry = mock(() => new Promise(() => {}));
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      void result.current.addNumber(CATEGORY.id, GLASSES_FIELD.id, 250);
    });

    expect(totalOf(result.current.entries)).toBe(250);
    expect(createEntry).toHaveBeenCalledWith({
      category_id: CATEGORY.id,
      entry_date: TODAY,
      values: [{ field_id: GLASSES_FIELD.id, value: '250' }],
    });
  });

  it('rolls back only the failed tap and keeps the successful ones', async () => {
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    let call = 0;
    createEntry = mock(() => {
      call += 1;
      return call === 2
        ? Promise.reject(new Error('server exploded'))
        : Promise.resolve(savedEntry(100 + call, 1));
    });

    await act(async () => {
      await Promise.all([
        result.current.addNumber(CATEGORY.id, GLASSES_FIELD.id, 1),
        result.current.addNumber(CATEGORY.id, GLASSES_FIELD.id, 1),
        result.current.addNumber(CATEGORY.id, GLASSES_FIELD.id, 1),
      ]);
    });

    expect(totalOf(result.current.entries)).toBe(2);
    expect(result.current.error).toBe('server exploded');
  });

  it('keeps an in-flight increment when a refetch lands mid-request', async () => {
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    const pendingCreate = deferred<Entry>();
    createEntry = mock(() => pendingCreate.promise);

    act(() => {
      void result.current.addNumber(CATEGORY.id, GLASSES_FIELD.id, 1);
    });
    expect(totalOf(result.current.entries)).toBe(1);

    // The refetch was answered by a server that had not seen the POST yet.
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await waitFor(() => expect(getAllEntries).toHaveBeenCalledTimes(2));
    expect(totalOf(result.current.entries)).toBe(1);

    await act(async () => {
      pendingCreate.resolve(savedEntry(11, 1));
      await Promise.resolve();
    });
    expect(totalOf(result.current.entries)).toBe(1);
  });

  it('counts a saved increment once after the refetch that returns it', async () => {
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.addNumber(CATEGORY.id, GLASSES_FIELD.id, 1);
    });
    expect(totalOf(result.current.entries)).toBe(1);

    getAllEntries = mock(() => Promise.resolve([ENTRY, savedEntry(11, 1)]));
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'));
    });

    await waitFor(() => expect(getAllEntries).toHaveBeenCalled());
    await waitFor(() => expect(totalOf(result.current.entries)).toBe(1));
  });

  it('takes the total from a refetch that saw another device write', async () => {
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    getAllEntries = mock(() => Promise.resolve([savedEntry(20, 3)]));
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'));
    });

    await waitFor(() => expect(totalOf(result.current.entries)).toBe(3));
  });
});
