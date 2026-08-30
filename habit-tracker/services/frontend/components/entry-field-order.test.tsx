// [review:need-review] PHASE-01/73-category-field-reorder
// summary: cross-shell test that both entry editors — the desktop modal and the mobile sheet — list a category's fields in the saved order rather than in whatever order the API serialised them, and post the values in that order too

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
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

/**
 * Sleep after the user moved Quality above Hours and saved.
 *
 * The reorder changes nothing but `order` — the ids stay put, so the rows stay
 * put in the table — and the array arrives in the sequence the backend happened
 * to serialise. Only `order` says what the user arranged.
 */
const REORDERED_CATEGORY: Category = {
  id: 1,
  name: 'Sleep',
  display_mode: 'form',
  streak_mode: 'build',
  is_active: true,
  created_at: TIMESTAMP,
  updated_at: TIMESTAMP,
  fields: [field(7, 'Hours', 1), field(8, 'Quality', 0)],
};

const SAVED_ORDER = ['Quality', 'Hours'];

let createEntry: ReturnType<typeof mock>;

// Declares the whole surface on purpose: bun fixes a module's export *names* the
// first time anything links against it and shares that registry across the run,
// so a partial mock here would delete members other suites reach for.
mock.module('@/lib/api', () => ({
  // The quick-mark directory and its one write path (#121). Present in every
  // api mock for the reason named above: bun fixes a module's export names on
  // first link, so a mock that omits an export deletes it for whoever links next.
  quickMarksAPI: {
    list: () => Promise.resolve([]),
    tap: () => Promise.resolve(null),
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
    getAll: () => Promise.resolve([REORDERED_CATEGORY]),
    getById: () => Promise.resolve(REORDERED_CATEGORY),
    getStreak: () => Promise.resolve(null),
    create: () => Promise.resolve(REORDERED_CATEGORY),
    update: () => Promise.resolve(REORDERED_CATEGORY),
    delete: () => Promise.resolve(undefined),
  },
  entriesAPI: {
    getAll: () => Promise.resolve([]),
    create: (data: unknown) => createEntry(data),
    update: () => Promise.resolve(null),
    delete: () => Promise.resolve(undefined),
    upsertChecklist: () => Promise.resolve({}),
  },
  tableAPI: { get: () => Promise.resolve({ days: [] }) },
}));

const { default: EntryForm } = await import('@/components/EntryForm');
const { default: EntryEditorSheet } = await import('@/components/mobile/EntryEditorSheet');

/** Names of the field inputs, in the order the editor rendered them. */
function renderedFieldNames(): string[] {
  return Array.from(document.querySelectorAll('label'))
    .map((label) => label.textContent?.trim() ?? '')
    .filter((text) => SAVED_ORDER.includes(text));
}

const noop = () => {};

beforeEach(() => {
  createEntry = mock(() => Promise.resolve(null));
});

afterEach(() => {
  cleanup();
});

describe('entry editors and the saved field order', () => {
  it('lists the fields in the saved order in the desktop modal', () => {
    render(
      <EntryForm categories={[REORDERED_CATEGORY]} onClose={noop} onSuccess={noop} />
    );

    // Rendering the array as it arrived would show the user the order they just
    // moved away from, on the very screen the reorder exists to arrange.
    expect(renderedFieldNames()).toEqual(SAVED_ORDER);
  });

  it('lists the fields in the saved order in the mobile sheet', () => {
    render(
      <EntryEditorSheet
        categories={[REORDERED_CATEGORY]}
        onCancel={noop}
        onSaved={noop}
      />
    );

    expect(renderedFieldNames()).toEqual(SAVED_ORDER);
  });

  it('posts the values in the saved order too', async () => {
    render(
      <EntryEditorSheet
        categories={[REORDERED_CATEGORY]}
        onCancel={noop}
        onSaved={noop}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'Done' }));

    await waitFor(() => expect(createEntry).toHaveBeenCalled());
    const payload = createEntry.mock.calls[0][0] as { values: { field_id: number }[] };
    // The payload is what the day plan and every re-read are built from; a list
    // whose order disagrees with the editor's is a second answer to a question
    // that has one.
    expect(payload.values.map((v) => v.field_id)).toEqual([8, 7]);
  });
});
