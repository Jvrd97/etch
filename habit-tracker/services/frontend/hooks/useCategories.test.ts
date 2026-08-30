// [review:need-review] PHASE-01/73-category-field-reorder
// summary: tests for useCategories and useCategoryDraft — list load, layout preference, delete, the field reorder with its stable row keys and its screen-reader announcement, the draft seeded in field order rather than in arrival order, and the field ids carried into the update payload so the backend diff-syncs instead of replacing

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import type { Category, Field } from '@/lib/api';

const TIMESTAMP = '2026-07-24T00:00:00Z';

function field(id: number, name: string, order: number): Field {
  return {
    id,
    category_id: 1,
    name,
    field_type: 'text',
    is_required: false,
    order,
    created_at: TIMESTAMP,
    updated_at: TIMESTAMP,
  };
}

const HOURS_FIELD = field(7, 'Hours', 0);
const QUALITY_FIELD = field(8, 'Quality', 1);

const CATEGORY: Category = {
  id: 1,
  name: 'Sleep',
  description: 'How I slept',
  color: '#123456',
  display_mode: 'form',
  streak_mode: 'build',
  group: 'Health',
  is_active: true,
  created_at: TIMESTAMP,
  updated_at: TIMESTAMP,
  fields: [HOURS_FIELD, QUALITY_FIELD],
};

const OTHER_CATEGORY: Category = { ...CATEGORY, id: 2, name: 'Mood', fields: [] };

let getAllCategories: ReturnType<typeof mock>;
let createCategory: ReturnType<typeof mock>;
let updateCategory: ReturnType<typeof mock>;
let deleteCategory: ReturnType<typeof mock>;

// Declares the whole surface on purpose: bun fixes a module's export *names* the
// first time anything links against it and shares that registry across the run,
// so a partial mock here would delete `tableAPI` for whichever file loads later.
mock.module('@/lib/api', () => ({
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
    getAll: (activeOnly?: boolean) => getAllCategories(activeOnly),
    getById: () => Promise.resolve(CATEGORY),
    getStreak: () => Promise.resolve(null),
    create: (data: unknown) => createCategory(data),
    update: (id: number, data: unknown) => updateCategory(id, data),
    delete: (id: number) => deleteCategory(id),
  },
  entriesAPI: {
    getAll: () => Promise.resolve([]),
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
  tableAPI: { get: () => Promise.resolve({ days: [] }) },
}));

/**
 * The same two fields as `CATEGORY`, handed over in the wrong sequence: ids
 * [8, 7] carrying orders [1, 0]. That is what a category looks like after a
 * reorder that swapped nothing but `order`, and nothing in the transport
 * promises the array itself comes back sorted.
 */
const UNORDERED_CATEGORY: Category = {
  ...CATEGORY,
  fields: [field(8, 'Quality', 1), field(7, 'Hours', 0)],
};

const { useCategories, useCategoryDraft, CATEGORY_LAYOUT_STORAGE_KEY, fieldMovedMessage } =
  await import('./useCategories');

beforeEach(() => {
  getAllCategories = mock(() => Promise.resolve([CATEGORY, OTHER_CATEGORY]));
  createCategory = mock(() => Promise.resolve(CATEGORY));
  updateCategory = mock(() => Promise.resolve(CATEGORY));
  deleteCategory = mock(() => Promise.resolve(undefined));
  localStorage.clear();
});

afterEach(() => {
  cleanup();
});

describe('useCategories', () => {
  it('loads every category, inactive ones included', async () => {
    const { result } = renderHook(() => useCategories());

    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.categories).toEqual([CATEGORY, OTHER_CATEGORY]);
    // An inactive category is still editable, so the management screen asks for
    // the unfiltered list rather than the active-only default.
    expect(getAllCategories).toHaveBeenCalledWith(false);
  });

  it('starts on the cards layout and remembers a switch to the list', async () => {
    const { result } = renderHook(() => useCategories());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.layout).toBe('cards');
    act(() => {
      result.current.setLayout('list');
    });

    expect(result.current.layout).toBe('list');
    expect(localStorage.getItem(CATEGORY_LAYOUT_STORAGE_KEY)).toBe('list');
  });

  it('restores the stored layout on mount', async () => {
    localStorage.setItem(CATEGORY_LAYOUT_STORAGE_KEY, 'list');
    const { result } = renderHook(() => useCategories());

    await waitFor(() => expect(result.current.layout).toBe('list'));
  });

  it('ignores a corrupted stored layout', async () => {
    localStorage.setItem(CATEGORY_LAYOUT_STORAGE_KEY, 'carousel');
    const { result } = renderHook(() => useCategories());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.layout).toBe('cards');
  });

  it('deletes a category and refetches the list', async () => {
    const { result } = renderHook(() => useCategories());
    await waitFor(() => expect(result.current.loading).toBe(false));

    getAllCategories = mock(() => Promise.resolve([OTHER_CATEGORY]));
    await act(async () => {
      await result.current.remove(1);
    });

    expect(deleteCategory).toHaveBeenCalledWith(1);
    expect(result.current.categories).toEqual([OTHER_CATEGORY]);
  });

  it('reports a failed delete instead of swallowing it', async () => {
    const { result } = renderHook(() => useCategories());
    await waitFor(() => expect(result.current.loading).toBe(false));

    deleteCategory = mock(() => Promise.reject(new Error('still referenced')));
    await act(async () => {
      await result.current.remove(1);
    });

    expect(result.current.error).toBe('still referenced');
    // The list is untouched, so the row the user tried to remove is still there.
    expect(result.current.categories).toEqual([CATEGORY, OTHER_CATEGORY]);
  });

  it('surfaces a load failure and lets the screen dismiss it', async () => {
    getAllCategories = mock(() => Promise.reject(new Error('network down')));
    const { result } = renderHook(() => useCategories());

    await waitFor(() => expect(result.current.error).toBe('network down'));
    expect(result.current.loading).toBe(false);

    act(() => {
      result.current.setError(null);
    });
    expect(result.current.error).toBeNull();
  });

  it('clears a stale load error once a reload succeeds', async () => {
    getAllCategories = mock(() => Promise.reject(new Error('network down')));
    const { result } = renderHook(() => useCategories());
    await waitFor(() => expect(result.current.error).toBe('network down'));

    getAllCategories = mock(() => Promise.resolve([CATEGORY]));
    await act(async () => {
      await result.current.reload();
    });

    // A banner outliving the failure it reports tells the user the screen is
    // broken while they are looking at fresh data.
    expect(result.current.error).toBeNull();
    expect(result.current.categories).toEqual([CATEGORY]);
  });

  it('clears a failed delete once the next load succeeds', async () => {
    const { result } = renderHook(() => useCategories());
    await waitFor(() => expect(result.current.loading).toBe(false));

    deleteCategory = mock(() => Promise.reject(new Error('still referenced')));
    await act(async () => {
      await result.current.remove(1);
    });
    expect(result.current.error).toBe('still referenced');

    deleteCategory = mock(() => Promise.resolve(undefined));
    await act(async () => {
      await result.current.remove(2);
    });
    expect(result.current.error).toBeNull();
  });
});

describe('useCategoryDraft', () => {
  const noop = () => {};

  it('starts a new category on one blank field so there is nothing to add first', () => {
    const { result } = renderHook(() =>
      useCategoryDraft({ category: null, onSaved: noop })
    );

    expect(result.current.name).toBe('');
    expect(result.current.fields).toHaveLength(1);
    expect(result.current.fields[0].name).toBe('');
  });

  it('seeds an edit from the category, keeping the field ids', () => {
    const { result } = renderHook(() =>
      useCategoryDraft({ category: CATEGORY, onSaved: noop })
    );

    expect(result.current.name).toBe('Sleep');
    expect(result.current.group).toBe('Health');
    expect(result.current.fields.map((f) => f.id)).toEqual([7, 8]);
  });

  it('seeds the draft in field order, not in the order the API listed them', () => {
    const { result } = renderHook(() =>
      useCategoryDraft({ category: UNORDERED_CATEGORY, onSaved: noop })
    );

    // `save` re-derives `order` from position, so a draft that trusted the
    // array would render the rows one way and save them the other — undoing the
    // reorder the user just made, simply by opening the editor.
    expect(result.current.fields.map((f) => f.id)).toEqual([7, 8]);
    expect(result.current.fields.map((f) => f.name)).toEqual(['Hours', 'Quality']);
  });

  it('announces where a moved field landed', () => {
    const { result } = renderHook(() =>
      useCategoryDraft({ category: CATEGORY, onSaved: noop })
    );

    // Nothing is announced before anything moves: a live region that speaks on
    // arrival trains the listener to ignore it.
    expect(result.current.moveAnnouncement).toBe('');

    act(() => result.current.moveField(1, 'up'));
    expect(result.current.moveAnnouncement).toBe(fieldMovedMessage(1));

    act(() => result.current.moveField(0, 'down'));
    expect(result.current.moveAnnouncement).toBe(fieldMovedMessage(2));
  });

  it('says nothing when the move went nowhere', () => {
    const { result } = renderHook(() =>
      useCategoryDraft({ category: CATEGORY, onSaved: noop })
    );

    act(() => result.current.moveField(0, 'up'));

    // The ends of the list are a no-op, and announcing one would tell the user
    // something happened when the list is exactly as it was.
    expect(result.current.moveAnnouncement).toBe('');
  });

  it('starts a new category under the Today heuristic, not switched on by hand', () => {
    const { result } = renderHook(() =>
      useCategoryDraft({ category: null, onSaved: noop })
    );

    expect(result.current.showInToday).toBeNull();
  });

  it('reads a category written before the column existed as "automatic"', () => {
    // Such a row deserializes without the key at all, which must land on the
    // same choice an explicit null does.
    const { result } = renderHook(() =>
      useCategoryDraft({ category: CATEGORY, onSaved: noop })
    );

    expect(CATEGORY.show_in_today).toBeUndefined();
    expect(result.current.showInToday).toBeNull();
  });

  it('sends the Today choice with the save, in all three states', async () => {
    const { result } = renderHook(() =>
      useCategoryDraft({ category: CATEGORY, onSaved: noop })
    );

    act(() => result.current.setShowInToday(true));
    await act(async () => {
      await result.current.save();
    });
    expect(updateCategory.mock.calls[0][1]).toMatchObject({ show_in_today: true });

    act(() => result.current.setShowInToday(false));
    await act(async () => {
      await result.current.save();
    });
    expect(updateCategory.mock.calls[1][1]).toMatchObject({ show_in_today: false });

    // Explicitly null, not omitted: that is what returns the category to the
    // heuristic instead of leaving the old override in place.
    act(() => result.current.setShowInToday(null));
    await act(async () => {
      await result.current.save();
    });
    expect(updateCategory.mock.calls[2][1]).toMatchObject({ show_in_today: null });
  });

  it('adds a field at the bottom and removes one by position', () => {
    const { result } = renderHook(() =>
      useCategoryDraft({ category: CATEGORY, onSaved: noop })
    );

    act(() => result.current.addField());
    expect(result.current.fields).toHaveLength(3);

    act(() => result.current.removeField(0));
    expect(result.current.fields.map((f) => f.id)).toEqual([8, undefined]);
  });

  it('moves a field up and down, carrying the whole field with it', () => {
    const { result } = renderHook(() =>
      useCategoryDraft({ category: CATEGORY, onSaved: noop })
    );

    act(() => result.current.moveField(1, 'up'));
    // The objects move whole, ids included: a swap that copied only the visible
    // text would hand the backend two fields it has to recreate.
    expect(result.current.fields.map((f) => f.id)).toEqual([8, 7]);
    expect(result.current.fields.map((f) => f.name)).toEqual(['Quality', 'Hours']);

    act(() => result.current.moveField(0, 'down'));
    expect(result.current.fields.map((f) => f.id)).toEqual([7, 8]);
  });

  it('leaves the list alone at either end', () => {
    const { result } = renderHook(() =>
      useCategoryDraft({ category: CATEGORY, onSaved: noop })
    );

    act(() => result.current.moveField(0, 'up'));
    expect(result.current.fields.map((f) => f.id)).toEqual([7, 8]);

    act(() => result.current.moveField(1, 'down'));
    expect(result.current.fields.map((f) => f.id)).toEqual([7, 8]);
  });

  it('gives every row a key that travels with it through a reorder', () => {
    const { result } = renderHook(() =>
      useCategoryDraft({ category: CATEGORY, onSaved: noop })
    );

    const keysBefore = result.current.fields.map((f) => f.key);
    expect(new Set(keysBefore).size).toBe(2);

    act(() => result.current.moveField(1, 'up'));

    // Stable per row, not per position: a positional key makes React reuse the
    // DOM of the row that used to sit there, and the text in the inputs swaps
    // back under the user.
    expect(result.current.fields.map((f) => f.key)).toEqual([keysBefore[1], keysBefore[0]]);

    act(() => result.current.addField());
    const keys = result.current.fields.map((f) => f.key);
    expect(new Set(keys).size).toBe(3);
  });

  it('re-derives order from the new positions and keeps the ids', async () => {
    const { result } = renderHook(() =>
      useCategoryDraft({ category: CATEGORY, onSaved: noop })
    );

    act(() => result.current.moveField(1, 'up'));
    await act(async () => {
      await result.current.save();
    });

    const payload = updateCategory.mock.calls[0][1] as {
      fields: Record<string, unknown>[];
    };
    expect(payload.fields).toEqual([
      expect.objectContaining({ id: 8, name: 'Quality', order: 0 }),
      expect.objectContaining({ id: 7, name: 'Hours', order: 1 }),
    ]);
    // The row key is the editor's own bookkeeping; the backend must not see it.
    expect(payload.fields.every((f) => !('key' in f))).toBe(true);
  });

  it('updates a field in place', () => {
    const { result } = renderHook(() =>
      useCategoryDraft({ category: CATEGORY, onSaved: noop })
    );

    act(() => result.current.updateField(1, { name: 'Restfulness' }));

    expect(result.current.fields[1].name).toBe('Restfulness');
    expect(result.current.fields[0].name).toBe('Hours');
  });

  it('sends the edited fields with their ids so the backend updates in place', async () => {
    const onSaved = mock(() => {});
    const { result } = renderHook(() => useCategoryDraft({ category: CATEGORY, onSaved }));

    act(() => result.current.updateField(1, { name: 'Restfulness' }));
    await act(async () => {
      await result.current.save();
    });

    expect(updateCategory).toHaveBeenCalledWith(1, expect.objectContaining({ name: 'Sleep' }));
    const payload = updateCategory.mock.calls[0][1] as { fields: { id?: number; name: string }[] };
    // Editing a field must keep its id: without it the backend replaces the
    // field and every value ever logged against it loses its column.
    expect(payload.fields).toEqual([
      expect.objectContaining({ id: 7, name: 'Hours', order: 0 }),
      expect.objectContaining({ id: 8, name: 'Restfulness', order: 1 }),
    ]);
    expect(onSaved).toHaveBeenCalled();
  });

  it('drops unnamed fields and re-indexes the order by position', async () => {
    const { result } = renderHook(() =>
      useCategoryDraft({ category: CATEGORY, onSaved: noop })
    );

    act(() => result.current.removeField(0));
    act(() => result.current.addField());
    await act(async () => {
      await result.current.save();
    });

    const payload = updateCategory.mock.calls[0][1] as { fields: { id?: number; order: number }[] };
    expect(payload.fields).toEqual([expect.objectContaining({ id: 8, order: 0 })]);
  });

  it('creates when there is no category behind the draft', async () => {
    const { result } = renderHook(() => useCategoryDraft({ category: null, onSaved: noop }));

    act(() => result.current.setName('Reading'));
    act(() => result.current.updateField(0, { name: 'Pages', field_type: 'number' }));
    await act(async () => {
      await result.current.save();
    });

    expect(createCategory).toHaveBeenCalledWith(
      expect.objectContaining({
        name: 'Reading',
        fields: [expect.objectContaining({ name: 'Pages', field_type: 'number', order: 0 })],
      })
    );
  });

  it('normalises an empty group to null rather than an empty string', async () => {
    const { result } = renderHook(() => useCategoryDraft({ category: null, onSaved: noop }));

    act(() => result.current.setName('Reading'));
    act(() => result.current.setGroup('   '));
    await act(async () => {
      await result.current.save();
    });

    expect(createCategory.mock.calls[0][0]).toMatchObject({ group: null });
  });

  it('keeps the sheet open and reports the message when the save is rejected', async () => {
    createCategory = mock(() => Promise.reject(new Error('name already taken')));
    const onSaved = mock(() => {});
    const { result } = renderHook(() => useCategoryDraft({ category: null, onSaved }));

    act(() => result.current.setName('Reading'));
    await act(async () => {
      await result.current.save();
    });

    expect(result.current.error).toBe('name already taken');
    expect(result.current.saving).toBe(false);
    expect(onSaved).not.toHaveBeenCalled();

    act(() => result.current.dismissError());
    expect(result.current.error).toBeNull();
  });

  it('warns while a checklist category still has no boolean field', () => {
    const { result } = renderHook(() =>
      useCategoryDraft({ category: CATEGORY, onSaved: noop })
    );

    expect(result.current.checklistNeedsBoolean).toBe(false);

    act(() => result.current.setDisplayMode('checklist'));
    // The backend rejects such a save, so the screen has to say so beforehand.
    expect(result.current.checklistNeedsBoolean).toBe(true);

    act(() => result.current.updateField(0, { field_type: 'boolean' }));
    expect(result.current.checklistNeedsBoolean).toBe(false);
  });

  it('posts a single save when Done is pressed twice in the same tick', async () => {
    const { result } = renderHook(() => useCategoryDraft({ category: CATEGORY, onSaved: noop }));

    await act(async () => {
      await Promise.all([result.current.save(), result.current.save()]);
    });

    expect(updateCategory).toHaveBeenCalledTimes(1);
  });
});
