// [review:need-review] PHASE-01/73-category-field-reorder
// summary: characterization tests for the desktop /categories page — the cards/list switch, the editor modal opening and closing, the field rows moving up and down with their ids, their DOM, their announcement and their focus, the category card listing fields in field order, and the sticky footer submitting the form it is not nested in

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { Category, Field } from '@/lib/api';

const TIMESTAMP = '2026-07-24T00:00:00Z';

const HOURS_FIELD: Field = {
  id: 7,
  category_id: 1,
  name: 'Hours',
  field_type: 'text',
  is_required: false,
  order: 0,
  created_at: TIMESTAMP,
  updated_at: TIMESTAMP,
};

const QUALITY_FIELD: Field = {
  id: 8,
  category_id: 1,
  name: 'Quality',
  field_type: 'text',
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
  fields: [HOURS_FIELD, QUALITY_FIELD],
};

let getAllCategories: ReturnType<typeof mock>;
let createCategory: ReturnType<typeof mock>;
let updateCategory: ReturnType<typeof mock>;
let deleteCategory: ReturnType<typeof mock>;

// Declares the whole surface on purpose: bun fixes a module's export *names* the
// first time anything links against it and shares that registry across the run,
// so a partial mock here would delete members other suites reach for.
mock.module('@/lib/api', () => ({
  // The goal board's client (#93). Present in every api mock for the same
  // reason the rest of the surface is: bun fixes a module's export names on
  // first link, so a mock that omits it deletes it for whoever runs next.
  goalsAPI: {
    get: () => Promise.resolve(null),
    patchMilestone: () => Promise.resolve(null),
  },
  // The quick-mark directory and its one write path (#121). Present in every
  // api mock for the reason named above: bun fixes a module's export names on
  // first link, so a mock that omits an export deletes it for whoever links next.
  quickMarksAPI: {
    list: () => Promise.resolve([]),
    tap: () => Promise.resolve(null),
    undo: () => Promise.resolve(null),
    sources: () => Promise.resolve([]),
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
  tableAPI: { get: () => Promise.resolve({ days: [] }) },
}));

// Same process-wide replacement rule as the API mock: the hooks other suites
// import have to stay present even though this screen only renders links.
mock.module('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
  usePathname: () => '/categories',
  useRouter: () => ({ push: () => {}, replace: () => {} }),
}));

const { default: CategoriesPage } = await import('./page');
const { fieldMovedMessage } = await import('@/hooks/useCategories');

/** Render the screen and wait for the first load to settle. */
async function renderPage() {
  render(<CategoriesPage />);
  await waitFor(() => expect(screen.getByLabelText('Card view')).toBeDefined());
}

beforeEach(() => {
  getAllCategories = mock(() => Promise.resolve([CATEGORY]));
  createCategory = mock(() => Promise.resolve(CATEGORY));
  updateCategory = mock(() => Promise.resolve(CATEGORY));
  deleteCategory = mock(() => Promise.resolve(undefined));
  localStorage.clear();
});

afterEach(() => {
  cleanup();
});

describe('/categories (desktop)', () => {
  it('lists the categories once the load settles', async () => {
    await renderPage();

    expect(screen.getByRole('heading', { name: 'Sleep' })).toBeDefined();
    // The management screen edits inactive categories too, so it asks for the
    // unfiltered list rather than the active-only default.
    expect(getAllCategories).toHaveBeenCalledWith(false);
  });

  it('switches between the cards and the list layout and remembers the choice', async () => {
    await renderPage();

    expect(screen.getByLabelText('Card view').getAttribute('aria-pressed')).toBe('true');

    fireEvent.click(screen.getByLabelText('List view'));

    await waitFor(() =>
      expect(screen.getByLabelText('List view').getAttribute('aria-pressed')).toBe('true')
    );
    expect(screen.getByLabelText('Card view').getAttribute('aria-pressed')).toBe('false');
    expect(localStorage.getItem('habit-tracker:categories-layout')).toBe('list');
  });

  it('opens the editor modal on a category and closes it again', async () => {
    await renderPage();

    fireEvent.click(screen.getByLabelText('Edit category'));
    expect(screen.getByRole('heading', { name: 'Edit category' })).toBeDefined();

    fireEvent.click(screen.getByLabelText('Close'));

    await waitFor(() =>
      expect(screen.queryByRole('heading', { name: 'Edit category' })).toBeNull()
    );
  });

  it('opens the modal on a blank draft for a new category', async () => {
    await renderPage();

    fireEvent.click(screen.getByRole('button', { name: 'New category' }));

    expect(screen.getByRole('heading', { name: 'New category' })).toBeDefined();
    expect(screen.getByRole('button', { name: 'Create' })).toBeDefined();
  });

  it('submits from the sticky footer, which sits outside the form', async () => {
    await renderPage();
    fireEvent.click(screen.getByLabelText('Edit category'));

    const submit = screen.getByRole('button', { name: 'Update' });
    // The footer is sticky, so it is a sibling of the form rather than a child:
    // without the `form` attribute the button would be inert.
    expect(submit.getAttribute('form')).toBe('category-form');
    expect(submit.closest('form')).toBeNull();
    fireEvent.click(submit);

    await waitFor(() => expect(updateCategory).toHaveBeenCalledTimes(1));
    expect(updateCategory.mock.calls[0][0]).toBe(1);
    // The modal closes and the list is refetched so the edit shows up.
    await waitFor(() =>
      expect(screen.queryByRole('heading', { name: 'Edit category' })).toBeNull()
    );
    expect(getAllCategories.mock.calls.length).toBeGreaterThan(1);
  });

  it('moves a field up and saves the new order with the ids intact', async () => {
    await renderPage();
    fireEvent.click(screen.getByLabelText('Edit category'));

    fireEvent.click(screen.getByRole('button', { name: 'Move field 2 up' }));
    fireEvent.click(screen.getByRole('button', { name: 'Update' }));

    await waitFor(() => expect(updateCategory).toHaveBeenCalled());
    const payload = updateCategory.mock.calls[0][1] as { fields: { id?: number }[] };
    // A reorder must not read as delete-and-recreate: the ids are what keep the
    // logged values attached to the fields they were logged against.
    expect(payload.fields).toEqual([
      expect.objectContaining({ id: 8, name: 'Quality', order: 0 }),
      expect.objectContaining({ id: 7, name: 'Hours', order: 1 }),
    ]);
  });

  it('has nowhere to go at either end of the field list', async () => {
    await renderPage();
    fireEvent.click(screen.getByLabelText('Edit category'));

    expect(
      (screen.getByRole('button', { name: 'Move field 1 up' }) as HTMLButtonElement).disabled
    ).toBe(true);
    expect(
      (screen.getByRole('button', { name: 'Move field 2 down' }) as HTMLButtonElement).disabled
    ).toBe(true);
    expect(
      (screen.getByRole('button', { name: 'Move field 2 up' }) as HTMLButtonElement).disabled
    ).toBe(false);
  });

  it('carries the row DOM with the field, so the inputs do not swap contents', async () => {
    await renderPage();
    fireEvent.click(screen.getByLabelText('Edit category'));

    const secondNameInput = screen.getByLabelText('Field 2 name');
    fireEvent.click(screen.getByRole('button', { name: 'Move field 2 up' }));

    // Index-keyed rows would reuse the DOM already sitting at position 1,
    // taking the focus and the caret of whoever was typing with them.
    expect(screen.getByLabelText('Field 1 name')).toBe(secondNameInput);
    expect((screen.getByLabelText('Field 1 name') as HTMLInputElement).value).toBe('Quality');
  });

  it('announces where the moved field landed', async () => {
    await renderPage();
    fireEvent.click(screen.getByLabelText('Edit category'));

    fireEvent.click(screen.getByRole('button', { name: 'Move field 2 up' }));

    // Without the live region the reorder is silent: the rows swap places and a
    // screen reader has nothing to report.
    expect(screen.getByRole('status').textContent).toBe(fieldMovedMessage(1));
  });

  it('keeps the focus on a button that still does something after a move', async () => {
    await renderPage();
    fireEvent.click(screen.getByLabelText('Edit category'));

    fireEvent.click(screen.getByRole('button', { name: 'Move field 2 up' }));

    // The pressed button travelled with its row to position 1, where "up" is
    // disabled: leaving focus there strands the keyboard on an inert control,
    // so it moves to the button that undoes the move.
    expect(document.activeElement).toBe(
      screen.getByRole('button', { name: 'Move field 1 down' })
    );
  });

  it('lists the fields on a category card in field order, not in arrival order', async () => {
    // The API is free to serialise the fields in any order; only `order` says
    // what the user arranged.
    getAllCategories = mock(() =>
      Promise.resolve([{ ...CATEGORY, fields: [QUALITY_FIELD, HOURS_FIELD] }])
    );
    await renderPage();

    const names = Array.from(document.querySelectorAll('li')).map((li) =>
      li.textContent?.trim()
    );
    expect(names).toEqual(['Hourstext', 'Qualitytext']);
  });

  it('deletes a category only after the user confirms', async () => {
    await renderPage();
    const originalConfirm = window.confirm;

    window.confirm = () => false;
    fireEvent.click(screen.getByLabelText('Delete category'));
    expect(deleteCategory).not.toHaveBeenCalled();

    window.confirm = () => true;
    fireEvent.click(screen.getByLabelText('Delete category'));
    await waitFor(() => expect(deleteCategory).toHaveBeenCalledWith(1));

    window.confirm = originalConfirm;
  });
});
