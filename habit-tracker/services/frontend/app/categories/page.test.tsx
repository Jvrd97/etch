// [review:need-review] PHASE-01/42-mobile-categories-and-detail
// summary: characterization tests for the desktop /categories page — the cards/list switch, the editor modal opening and closing, and the sticky footer submitting the form it is not nested in

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

const CATEGORY: Category = {
  id: 1,
  name: 'Sleep',
  display_mode: 'form',
  streak_mode: 'build',
  is_active: true,
  created_at: TIMESTAMP,
  updated_at: TIMESTAMP,
  fields: [HOURS_FIELD],
};

let getAllCategories: ReturnType<typeof mock>;
let createCategory: ReturnType<typeof mock>;
let updateCategory: ReturnType<typeof mock>;
let deleteCategory: ReturnType<typeof mock>;

// Declares the whole surface on purpose: bun fixes a module's export *names* the
// first time anything links against it and shares that registry across the run,
// so a partial mock here would delete members other suites reach for.
mock.module('@/lib/api', () => ({
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
