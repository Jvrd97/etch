// [review:need-review] PHASE-01/41-mobile-entries-fullscreen-sheet, PHASE-01/42-mobile-categories-and-detail
// summary: tests for useEntryDraft — seeding, category switching, create vs update dispatch and the single save-failure text shared by all three editors

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import type { Category, Entry, Field } from '@/lib/api';

const TIMESTAMP = '2026-07-24T00:00:00Z';
const TODAY = '2026-07-24';

function field(id: number, name: string): Field {
  return {
    id,
    category_id: 1,
    name,
    field_type: 'text',
    is_required: false,
    order: id,
    created_at: TIMESTAMP,
    updated_at: TIMESTAMP,
  };
}

const CATEGORY: Category = {
  id: 1,
  name: 'Sleep',
  display_mode: 'form',
  streak_mode: 'build',
  is_active: true,
  created_at: TIMESTAMP,
  updated_at: TIMESTAMP,
  fields: [field(7, 'Hours')],
};

const OTHER_CATEGORY: Category = {
  ...CATEGORY,
  id: 2,
  name: 'Mood',
  fields: [field(8, 'Score')],
};

const ENTRY: Entry = {
  id: 10,
  category_id: 1,
  entry_date: '2026-07-20',
  notes: 'slept well',
  created_at: TIMESTAMP,
  updated_at: TIMESTAMP,
  values: [{ id: 1, entry_id: 10, field_id: 7, value: '8' }],
};

let createEntry: ReturnType<typeof mock>;
let updateEntry: ReturnType<typeof mock>;

// The whole module is replaced process-wide, so the members other suites reach
// for have to stay present even though this one only drives create/update.
mock.module('@/lib/api', () => ({
  categoriesAPI: {
    getAll: () => Promise.resolve([CATEGORY, OTHER_CATEGORY]),
    getById: () => Promise.resolve(CATEGORY),
    getStreak: () => Promise.resolve(null),
    create: () => Promise.resolve(CATEGORY),
    update: () => Promise.resolve(CATEGORY),
    delete: () => Promise.resolve(),
  },
  entriesAPI: {
    getAll: () => Promise.resolve([ENTRY]),
    create: (data: unknown) => createEntry(data),
    update: (id: number, data: unknown) => updateEntry(id, data),
    delete: () => Promise.resolve(),
    upsertChecklist: () => Promise.resolve({}),
  },
  tableAPI: { get: () => Promise.resolve({ days: [] }) },
}));

mock.module('@/lib/date', () => ({ todayISO: () => TODAY }));

const { useEntryDraft, SAVE_ENTRY_ERROR } = await import('./useEntryDraft');

beforeEach(() => {
  createEntry = mock(() => Promise.resolve(ENTRY));
  updateEntry = mock(() => Promise.resolve(ENTRY));
});

afterEach(() => {
  cleanup();
});

describe('useEntryDraft (create)', () => {
  it('starts empty, on today, in the first category', () => {
    const { result } = renderHook(() =>
      useEntryDraft({ categories: [CATEGORY, OTHER_CATEGORY], onSaved: () => {} })
    );

    expect(result.current.categoryId).toBe(1);
    expect(result.current.entryDate).toBe(TODAY);
    expect(result.current.notes).toBe('');
    expect(result.current.values).toEqual({});
    expect(result.current.category).toEqual(CATEGORY);
  });

  it('honours an explicit start category and date', () => {
    const { result } = renderHook(() =>
      useEntryDraft({
        categories: [CATEGORY, OTHER_CATEGORY],
        categoryId: 2,
        date: '2026-07-01',
        onSaved: () => {},
      })
    );

    expect(result.current.category).toEqual(OTHER_CATEGORY);
    expect(result.current.entryDate).toBe('2026-07-01');
  });

  it('drops typed values when the category changes, since field ids are category-scoped', () => {
    const { result } = renderHook(() =>
      useEntryDraft({ categories: [CATEGORY, OTHER_CATEGORY], onSaved: () => {} })
    );

    act(() => result.current.setValue(7, '9'));
    expect(result.current.values).toEqual({ 7: '9' });

    act(() => result.current.setCategoryId(2));
    expect(result.current.values).toEqual({});
  });

  it('creates the entry with one value per category field', async () => {
    const onSaved = mock(() => {});
    const { result } = renderHook(() =>
      useEntryDraft({ categories: [CATEGORY, OTHER_CATEGORY], onSaved })
    );

    act(() => result.current.setValue(7, '9'));
    act(() => result.current.setNotes('short night'));
    await act(async () => {
      await result.current.save();
    });

    expect(createEntry.mock.calls[0][0]).toEqual({
      category_id: 1,
      entry_date: TODAY,
      notes: 'short night',
      values: [{ field_id: 7, value: '9' }],
    });
    expect(updateEntry).not.toHaveBeenCalled();
    expect(onSaved).toHaveBeenCalledTimes(1);
  });

  it('refuses to save without a category, instead of posting category_id 0', async () => {
    const onSaved = mock(() => {});
    const { result } = renderHook(() => useEntryDraft({ categories: [], onSaved }));

    await act(async () => {
      await result.current.save();
    });

    expect(createEntry).not.toHaveBeenCalled();
    expect(onSaved).not.toHaveBeenCalled();
    expect(result.current.error).not.toBeNull();
  });
});

describe('useEntryDraft (edit)', () => {
  it('seeds the draft from the entry being edited', () => {
    const { result } = renderHook(() =>
      useEntryDraft({ categories: [CATEGORY], entry: ENTRY, onSaved: () => {} })
    );

    expect(result.current.categoryId).toBe(1);
    expect(result.current.entryDate).toBe('2026-07-20');
    expect(result.current.notes).toBe('slept well');
    expect(result.current.values).toEqual({ 7: '8' });
  });

  it('updates the existing entry instead of creating a second one', async () => {
    const onSaved = mock(() => {});
    const { result } = renderHook(() =>
      useEntryDraft({ categories: [CATEGORY], entry: ENTRY, onSaved })
    );

    act(() => result.current.setValue(7, '6'));
    await act(async () => {
      await result.current.save();
    });

    expect(createEntry).not.toHaveBeenCalled();
    expect(updateEntry.mock.calls[0]).toEqual([
      10,
      {
        entry_date: '2026-07-20',
        notes: 'slept well',
        values: [{ field_id: 7, value: '6' }],
      },
    ]);
    expect(onSaved).toHaveBeenCalledTimes(1);
  });

  it('sends no notes at all once the user clears them', async () => {
    const { result } = renderHook(() =>
      useEntryDraft({ categories: [CATEGORY], entry: ENTRY, onSaved: () => {} })
    );

    act(() => result.current.setNotes(''));
    await act(async () => {
      await result.current.save();
    });

    expect(updateEntry.mock.calls[0][1]).toEqual({
      entry_date: '2026-07-20',
      notes: undefined,
      values: [{ field_id: 7, value: '8' }],
    });
  });
});

describe('useEntryDraft (failure)', () => {
  it('reports one text for a rejected create and stays unsaved', async () => {
    createEntry = mock(() => Promise.reject(new Error('server exploded')));
    const onSaved = mock(() => {});
    const { result } = renderHook(() => useEntryDraft({ categories: [CATEGORY], onSaved }));

    await act(async () => {
      await result.current.save();
    });

    expect(result.current.error).toBe('server exploded');
    expect(result.current.saving).toBe(false);
    expect(onSaved).not.toHaveBeenCalled();
  });

  it('falls back to the shared message when the rejection carries no message', async () => {
    updateEntry = mock(() => Promise.reject('nope'));
    const { result } = renderHook(() =>
      useEntryDraft({ categories: [CATEGORY], entry: ENTRY, onSaved: () => {} })
    );

    await act(async () => {
      await result.current.save();
    });

    expect(result.current.error).toBe(SAVE_ENTRY_ERROR);
  });

  it('lets the editor dismiss the banner and retry', async () => {
    createEntry = mock(() => Promise.reject(new Error('server exploded')));
    const { result } = renderHook(() =>
      useEntryDraft({ categories: [CATEGORY], onSaved: () => {} })
    );

    await act(async () => {
      await result.current.save();
    });
    act(() => result.current.dismissError());
    expect(result.current.error).toBeNull();

    createEntry = mock(() => Promise.resolve(ENTRY));
    await act(async () => {
      await result.current.save();
    });
    await waitFor(() => expect(result.current.error).toBeNull());
    expect(createEntry).toHaveBeenCalledTimes(1);
  });

  it('marks itself busy while the save is in flight', async () => {
    let release!: () => void;
    createEntry = mock(
      () =>
        new Promise((resolve) => {
          release = () => resolve(ENTRY);
        })
    );
    const { result } = renderHook(() =>
      useEntryDraft({ categories: [CATEGORY], onSaved: () => {} })
    );

    let saved!: Promise<void>;
    act(() => {
      saved = result.current.save();
    });
    expect(result.current.saving).toBe(true);

    await act(async () => {
      release();
      await saved;
    });
    expect(result.current.saving).toBe(false);
  });

  it('ignores a second save fired before the first one settles', async () => {
    let release!: () => void;
    createEntry = mock(
      () =>
        new Promise((resolve) => {
          release = () => resolve(ENTRY);
        })
    );
    const { result } = renderHook(() =>
      useEntryDraft({ categories: [CATEGORY], onSaved: () => {} })
    );

    // Both calls happen in one tick, so `saving` has not re-rendered yet — only
    // a ref can tell the second call that a request is already in flight.
    let first!: Promise<void>;
    let second!: Promise<void>;
    act(() => {
      first = result.current.save();
      second = result.current.save();
    });

    await act(async () => {
      release();
      await Promise.all([first, second]);
    });
    expect(createEntry).toHaveBeenCalledTimes(1);
  });
});
