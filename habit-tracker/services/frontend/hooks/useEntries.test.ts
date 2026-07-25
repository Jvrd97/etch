// [review:need-review] PHASE-01/41-mobile-entries-fullscreen-sheet, PHASE-01/42-mobile-categories-and-detail
// summary: tests for useEntries — initial load, date grouping (memoised), category filter refetch, error surfacing, silent refetch when the app becomes visible again and reload after a mutation

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

const OTHER_CATEGORY: Category = { ...CATEGORY, id: 2, name: 'Mood' };

function entry(id: number, date: string, categoryId = 1): Entry {
  return {
    id,
    category_id: categoryId,
    entry_date: date,
    created_at: TIMESTAMP,
    updated_at: TIMESTAMP,
    values: [],
  };
}

const TODAY_ENTRY = entry(10, '2026-07-24');
const SAME_DAY_ENTRY = entry(11, '2026-07-24');
const YESTERDAY_ENTRY = entry(12, '2026-07-23');

let getAllEntries: ReturnType<typeof mock>;
let getAllCategories: ReturnType<typeof mock>;

// The export *names* of a mocked module are fixed the first time any test file
// links against it, and bun shares that registry across the whole run. Every
// mock of `@/lib/api` therefore has to declare the full surface the app imports,
// even the parts this file never calls — otherwise whichever file happens to
// load first decides that `tableAPI` does not exist.
mock.module('@/lib/api', () => ({
  onboardingAPI: { draft: () => Promise.resolve({ operations: [] }) },
  insightsAPI: {
    getAll: () => Promise.resolve([]),
    getById: () => Promise.resolve(null),
    create: () => Promise.resolve(null),
  },
  categoriesAPI: {
    getAll: () => getAllCategories(),
    getById: () => Promise.resolve(CATEGORY),
    getStreak: () => Promise.resolve(null),
    create: () => Promise.resolve(CATEGORY),
    update: () => Promise.resolve(CATEGORY),
    delete: () => Promise.resolve(undefined),
  },
  entriesAPI: {
    getAll: (params?: unknown) => getAllEntries(params),
    create: () => Promise.resolve(TODAY_ENTRY),
    update: () => Promise.resolve(TODAY_ENTRY),
    delete: () => Promise.resolve(undefined),
  },
  tableAPI: { get: () => Promise.resolve({ days: [] }) },
}));

const { useEntries } = await import('./useEntries');

beforeEach(() => {
  getAllCategories = mock(() => Promise.resolve([CATEGORY, OTHER_CATEGORY]));
  getAllEntries = mock(() =>
    Promise.resolve([TODAY_ENTRY, SAME_DAY_ENTRY, YESTERDAY_ENTRY])
  );
});

afterEach(() => {
  cleanup();
});

describe('useEntries', () => {
  it('loads entries and categories, spinning only on the first load', async () => {
    const { result } = renderHook(() => useEntries());

    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.entries).toHaveLength(3);
    expect(result.current.categories).toEqual([CATEGORY, OTHER_CATEGORY]);
  });

  it('groups entries by date for rendering', async () => {
    const { result } = renderHook(() => useEntries());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.grouped).toEqual([
      ['2026-07-24', [TODAY_ENTRY, SAME_DAY_ENTRY]],
      ['2026-07-23', [YESTERDAY_ENTRY]],
    ]);
  });

  it('keeps the grouping identity stable while the entries do not change', async () => {
    const { result, rerender } = renderHook(() => useEntries());
    await waitFor(() => expect(result.current.loading).toBe(false));

    const grouped = result.current.grouped;
    rerender();

    // A fresh array on every render turns the hook's public contract into a
    // permanent change for any memo or effect a screen hangs off it.
    expect(result.current.grouped).toBe(grouped);
  });

  it('resolves the category behind an entry', async () => {
    const { result } = renderHook(() => useEntries());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.categoryOf(TODAY_ENTRY)).toEqual(CATEGORY);
    expect(result.current.categoryOf(entry(99, '2026-07-24', 404))).toBeUndefined();
  });

  it('refetches with the category filter applied', async () => {
    const { result } = renderHook(() => useEntries());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      result.current.setFilterCategory(2);
    });
    await waitFor(() =>
      expect(getAllEntries).toHaveBeenLastCalledWith(
        expect.objectContaining({ categoryId: 2 })
      )
    );
  });

  it('sends no category filter when the filter is cleared', async () => {
    const { result } = renderHook(() => useEntries());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(getAllEntries).toHaveBeenLastCalledWith(
      expect.objectContaining({ categoryId: undefined })
    );
  });

  it('surfaces a load failure and lets the screen dismiss it', async () => {
    getAllEntries = mock(() => Promise.reject(new Error('network down')));
    const { result } = renderHook(() => useEntries());

    await waitFor(() => expect(result.current.error).toBe('network down'));
    expect(result.current.loading).toBe(false);

    act(() => {
      result.current.setError(null);
    });
    expect(result.current.error).toBeNull();
  });

  it('refetches silently when the app becomes visible again', async () => {
    const { result } = renderHook(() => useEntries());
    await waitFor(() => expect(result.current.loading).toBe(false));
    const loadsBefore = getAllEntries.mock.calls.length;

    getAllEntries = mock(() => Promise.resolve([TODAY_ENTRY]));
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'));
    });

    // Installed as a PWA the document is never reloaded, so without this the
    // list keeps showing whatever was fetched when the app was launched.
    await waitFor(() => expect(result.current.entries).toEqual([TODAY_ENTRY]));
    expect(getAllEntries.mock.calls.length).toBeGreaterThan(0);
    expect(loadsBefore).toBeGreaterThan(0);
    // Silent: the list stays on screen instead of collapsing into a spinner.
    expect(result.current.loading).toBe(false);
  });

  it('keeps a caller-set error across a silent refresh', async () => {
    const { result } = renderHook(() => useEntries());
    await waitFor(() => expect(result.current.loading).toBe(false));

    // A failed delete is reported by the screen, not by the fetch. Returning to
    // the app refetches the list, and clearing the whole banner there would wipe
    // the only trace of the failure the moment the user comes back to read it.
    act(() => {
      result.current.setError('Failed to delete entry');
    });

    getAllEntries = mock(() => Promise.resolve([TODAY_ENTRY]));
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'));
    });

    await waitFor(() => expect(result.current.entries).toEqual([TODAY_ENTRY]));
    expect(result.current.error).toBe('Failed to delete entry');
  });

  it('retires a load failure once the list loads again', async () => {
    getAllEntries = mock(() => Promise.reject(new Error('network down')));
    const { result } = renderHook(() => useEntries());
    await waitFor(() => expect(result.current.error).toBe('network down'));

    getAllEntries = mock(() => Promise.resolve([TODAY_ENTRY]));
    await act(async () => {
      await result.current.reload();
    });

    expect(result.current.error).toBeNull();
  });

  it('reloads after a mutation without blanking the list', async () => {
    const { result } = renderHook(() => useEntries());
    await waitFor(() => expect(result.current.loading).toBe(false));

    getAllEntries = mock(() => Promise.resolve([TODAY_ENTRY]));
    await act(async () => {
      await result.current.reload();
    });

    expect(result.current.loading).toBe(false);
    expect(result.current.entries).toEqual([TODAY_ENTRY]);
  });
});
