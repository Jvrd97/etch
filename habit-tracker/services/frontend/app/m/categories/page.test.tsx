// [review:need-review] PHASE-01/42-mobile-categories-and-detail
// summary: integration tests for /m/categories — create a category, add and remove fields and have the edits actually persist, plus the layout rule that no form control sits two-in-a-row on a narrow screen

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

const HOURS_FIELD = field(7, 'Hours', 0);
const QUALITY_FIELD = field(8, 'Quality', 1);

const CATEGORY: Category = {
  id: 1,
  name: 'Sleep',
  color: '#123456',
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
// so a partial mock here would delete `tableAPI` for whichever file loads later.
mock.module('@/lib/api', () => ({
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

const { default: MobileCategoriesPage } = await import('./page');
const { NEW_CATEGORY_SHEET_TITLE } = await import('@/lib/ui-constants');

/** Render the screen and wait for the first load to settle. */
async function renderPage() {
  render(<MobileCategoriesPage />);
  await waitFor(() => expect(screen.getByText('Sleep')).toBeDefined());
}

/** The open editor sheet. */
function sheet(): HTMLElement {
  return screen.getByRole('dialog');
}

beforeEach(() => {
  getAllCategories = mock(() => Promise.resolve([CATEGORY]));
  createCategory = mock(() => Promise.resolve(CATEGORY));
  updateCategory = mock(() => Promise.resolve(CATEGORY));
  deleteCategory = mock(() => Promise.resolve(undefined));
});

afterEach(() => {
  cleanup();
});

describe('/m/categories', () => {
  it('lists the categories with a link into their detail screen', async () => {
    await renderPage();

    const link = screen.getByRole('link', { name: /Sleep/ });
    expect(link.getAttribute('href')).toBe('/m/categories/1');
  });

  it('creates a category from the sheet', async () => {
    await renderPage();

    fireEvent.click(screen.getByRole('button', { name: 'New category' }));
    expect(screen.getByRole('dialog', { name: NEW_CATEGORY_SHEET_TITLE })).toBeDefined();

    fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: 'Reading' } });
    fireEvent.change(screen.getByLabelText('Field 1 name'), { target: { value: 'Pages' } });
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));

    await waitFor(() => expect(createCategory).toHaveBeenCalled());
    expect(createCategory.mock.calls[0][0]).toMatchObject({
      name: 'Reading',
      fields: [{ name: 'Pages', order: 0 }],
    });
    // The sheet closes on success, back to the list.
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  it('adds a field and saves it', async () => {
    await renderPage();

    fireEvent.click(screen.getByRole('button', { name: 'Edit Sleep' }));
    fireEvent.click(screen.getByRole('button', { name: 'Add field' }));
    fireEvent.change(screen.getByLabelText('Field 3 name'), { target: { value: 'Dreams' } });
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));

    await waitFor(() => expect(updateCategory).toHaveBeenCalled());
    const payload = updateCategory.mock.calls[0][1] as { fields: { name: string }[] };
    expect(payload.fields.map((f) => f.name)).toEqual(['Hours', 'Quality', 'Dreams']);
  });

  it('removes a field and saves the removal', async () => {
    await renderPage();

    fireEvent.click(screen.getByRole('button', { name: 'Edit Sleep' }));
    fireEvent.click(screen.getByRole('button', { name: 'Remove field 1' }));
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));

    await waitFor(() => expect(updateCategory).toHaveBeenCalled());
    const payload = updateCategory.mock.calls[0][1] as { fields: { id?: number }[] };
    expect(payload.fields).toEqual([expect.objectContaining({ id: 8, order: 0 })]);
  });

  it('renames a field without losing its id, so the edit really persists', async () => {
    await renderPage();

    fireEvent.click(screen.getByRole('button', { name: 'Edit Sleep' }));
    fireEvent.change(screen.getByLabelText('Field 1 name'), { target: { value: 'Slept' } });
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));

    await waitFor(() => expect(updateCategory).toHaveBeenCalled());
    const payload = updateCategory.mock.calls[0][1] as { fields: { id?: number; name: string }[] };
    expect(payload.fields[0]).toMatchObject({ id: 7, name: 'Slept' });
  });

  it('reloads the list once the save went through', async () => {
    await renderPage();
    const loadsBefore = getAllCategories.mock.calls.length;

    fireEvent.click(screen.getByRole('button', { name: 'Edit Sleep' }));
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));

    await waitFor(() =>
      expect(getAllCategories.mock.calls.length).toBeGreaterThan(loadsBefore)
    );
  });

  it('keeps the sheet open and shows why when the save is rejected', async () => {
    await renderPage();
    updateCategory = mock(() => Promise.reject(new Error('name already taken')));

    fireEvent.click(screen.getByRole('button', { name: 'Edit Sleep' }));
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));

    await waitFor(() => expect(screen.getByText('name already taken')).toBeDefined());
    expect(screen.queryByRole('dialog')).not.toBeNull();
  });

  it('never puts two form controls side by side in the sheet', async () => {
    await renderPage();
    fireEvent.click(screen.getByRole('button', { name: 'Edit Sleep' }));

    // The desktop modal packs Display/Streak mode and Colour/Active into
    // `grid-cols-2`, which on a phone leaves two unusable half-width controls.
    const columns = sheet().querySelectorAll('[class*="grid-cols-2"], [class*="grid-cols-3"]');
    expect(columns).toHaveLength(0);
  });

  it('discards the draft when the sheet is cancelled', async () => {
    await renderPage();

    fireEvent.click(screen.getByRole('button', { name: 'Edit Sleep' }));
    fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: 'Rest' } });
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(updateCategory).not.toHaveBeenCalled();
  });

  it('deletes a category once the confirmation is accepted', async () => {
    const confirmSpy = mock(() => true);
    globalThis.confirm = confirmSpy as unknown as typeof globalThis.confirm;
    await renderPage();

    fireEvent.click(screen.getByRole('button', { name: 'Delete Sleep' }));

    await waitFor(() => expect(deleteCategory).toHaveBeenCalledWith(1));
    expect(confirmSpy).toHaveBeenCalled();
  });

  it('leaves the category alone when the confirmation is declined', async () => {
    globalThis.confirm = (() => false) as unknown as typeof globalThis.confirm;
    await renderPage();

    fireEvent.click(screen.getByRole('button', { name: 'Delete Sleep' }));

    expect(deleteCategory).not.toHaveBeenCalled();
  });

  it('offers a way in when there is no category yet', async () => {
    getAllCategories = mock(() => Promise.resolve([]));
    render(<MobileCategoriesPage />);

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Create category' })).toBeDefined()
    );
    fireEvent.click(screen.getByRole('button', { name: 'Create category' }));
    expect(screen.getByRole('dialog', { name: NEW_CATEGORY_SHEET_TITLE })).toBeDefined();
  });
});
