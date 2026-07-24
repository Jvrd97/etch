// [review:need-review] PHASE-01/41-mobile-entries-fullscreen-sheet, PHASE-01/42-mobile-categories-and-detail
// summary: integration tests for /m/entries — create, edit, cancel and delete driven through the shared EntryEditorSheet, plus the ?new=1 deep link that opens the editor on mount

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { Category, Entry, Field } from '@/lib/api';

const TIMESTAMP = '2026-07-24T00:00:00Z';
const TODAY = '2026-07-24';

const HOURS_FIELD: Field = {
  id: 7,
  category_id: 1,
  name: 'Hours',
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
  fields: [HOURS_FIELD],
};

const ENTRY: Entry = {
  id: 10,
  category_id: 1,
  entry_date: TODAY,
  notes: 'slept well',
  created_at: TIMESTAMP,
  updated_at: TIMESTAMP,
  values: [{ id: 1, entry_id: 10, field_id: 7, value: '8' }],
};

let getAllCategories: ReturnType<typeof mock>;
let getAllEntries: ReturnType<typeof mock>;
let createEntry: ReturnType<typeof mock>;
let updateEntry: ReturnType<typeof mock>;
let deleteEntry: ReturnType<typeof mock>;
let searchParams: URLSearchParams;

// Same process-wide replacement rule as the API mock: the hooks other suites
// import have to stay present even though this screen only reads the query.
mock.module('next/navigation', () => ({
  useSearchParams: () => searchParams,
  useParams: () => ({}),
  usePathname: () => '/m/entries',
  useRouter: () => ({ push: () => {}, replace: () => {} }),
}));

// Every mock of `@/lib/api` declares the full surface the app imports: bun fixes
// a module's export *names* the first time anything links against it and shares
// that registry across the run, so a partial mock here would delete `tableAPI`
// for whichever file loads later.
mock.module('@/lib/api', () => ({
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
    create: (data: unknown) => createEntry(data),
    update: (id: number, data: unknown) => updateEntry(id, data),
    delete: (id: number) => deleteEntry(id),
  },
  tableAPI: { get: () => Promise.resolve({ days: [] }) },
}));

mock.module('@/lib/date', () => ({ todayISO: () => TODAY }));

const { default: MobileEntriesPage } = await import('./page');
const { NEW_ENTRY_SHEET_TITLE } = await import('@/lib/ui-constants');

/** Render the screen and wait for the first load to settle. */
async function renderPage() {
  render(<MobileEntriesPage />);
  await waitFor(() => expect(screen.getByRole('heading', { name: 'Sleep' })).toBeDefined());
}

beforeEach(() => {
  searchParams = new URLSearchParams();
  getAllCategories = mock(() => Promise.resolve([CATEGORY]));
  getAllEntries = mock(() => Promise.resolve([ENTRY]));
  createEntry = mock(() => Promise.resolve(ENTRY));
  updateEntry = mock(() => Promise.resolve(ENTRY));
  deleteEntry = mock(() => Promise.resolve());
});

afterEach(() => {
  cleanup();
});

describe('/m/entries', () => {
  it('creates an entry through the full-screen sheet', async () => {
    await renderPage();

    fireEvent.click(screen.getByRole('button', { name: 'New entry' }));
    expect(screen.getByRole('dialog')).toBeDefined();

    fireEvent.change(screen.getByLabelText('Hours'), { target: { value: '9' } });
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));

    await waitFor(() => expect(createEntry).toHaveBeenCalledTimes(1));
    expect(createEntry.mock.calls[0][0]).toEqual({
      category_id: 1,
      entry_date: TODAY,
      notes: undefined,
      values: [{ field_id: 7, value: '9' }],
    });

    // The sheet closes and the list is refetched so the new entry shows up.
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(getAllEntries.mock.calls.length).toBeGreaterThan(1);
  });

  it('opens the create sheet straight away with ?new=1', async () => {
    searchParams = new URLSearchParams('new=1');
    render(<MobileEntriesPage />);

    // The mobile shell's "+" tab links here with ?new=1, so the deep link has to
    // land on the editor rather than on the list with one more tap to go.
    await waitFor(() =>
      expect(screen.getByRole('dialog', { name: NEW_ENTRY_SHEET_TITLE })).toBeDefined()
    );
  });

  it('stays on the list when no ?new=1 is given', async () => {
    await renderPage();

    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('edits an existing entry, prefilled with its stored values', async () => {
    await renderPage();

    fireEvent.click(screen.getByRole('button', { name: 'Edit Sleep entry' }));
    const hours = screen.getByLabelText('Hours') as HTMLInputElement;
    expect(hours.value).toBe('8');
    // An existing entry stays in the category it was logged into, so the shared
    // sheet drops the picker rather than offering a way to move it by accident.
    expect(screen.queryByLabelText('Category')).toBeNull();

    fireEvent.change(hours, { target: { value: '6' } });
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));

    await waitFor(() => expect(updateEntry).toHaveBeenCalledTimes(1));
    expect(updateEntry.mock.calls[0]).toEqual([
      10,
      {
        entry_date: TODAY,
        notes: 'slept well',
        values: [{ field_id: 7, value: '6' }],
      },
    ]);
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  it('discards the draft when the user cancels', async () => {
    await renderPage();

    fireEvent.click(screen.getByRole('button', { name: 'Edit Sleep entry' }));
    fireEvent.change(screen.getByLabelText('Hours'), { target: { value: '6' } });
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(updateEntry).not.toHaveBeenCalled();
  });

  it('keeps the sheet open and reports the failure when the save is rejected', async () => {
    createEntry = mock(() => Promise.reject(new Error('server exploded')));
    await renderPage();

    fireEvent.click(screen.getByRole('button', { name: 'New entry' }));
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));

    await waitFor(() => expect(screen.getByText('server exploded')).toBeDefined());
    expect(screen.getByRole('dialog')).toBeDefined();
    // The banner has to live inside the sheet: rendered behind it on the page it
    // is invisible, so the user sees Done do nothing and no reason why.
    expect(screen.getByText('server exploded').closest('[role="dialog"]')).not.toBeNull();
  });

  it('deletes an entry only after the user confirms', async () => {
    await renderPage();
    const originalConfirm = window.confirm;

    window.confirm = () => false;
    fireEvent.click(screen.getByRole('button', { name: 'Delete Sleep entry' }));
    expect(deleteEntry).not.toHaveBeenCalled();

    window.confirm = () => true;
    fireEvent.click(screen.getByRole('button', { name: 'Delete Sleep entry' }));
    await waitFor(() => expect(deleteEntry).toHaveBeenCalledWith(10));

    window.confirm = originalConfirm;
  });

  it('sends the user to Categories instead of opening an editor with nothing to log into', async () => {
    getAllCategories = mock(() => Promise.resolve([]));
    getAllEntries = mock(() => Promise.resolve([]));
    render(<MobileEntriesPage />);

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Create a category first' })).toBeDefined()
    );
    const link = screen.getByRole('link', { name: 'Go to Categories' });
    // The mobile twin, not the desktop route: MobileRestore only redirects into
    // /m once per session, so leaving the shell here is a one-way trip.
    expect(link.getAttribute('href')).toBe('/m/categories');
    // No way in, so no way to post an entry against category_id 0.
    expect(screen.queryByRole('button', { name: 'New entry' })).toBeNull();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('narrows the list to one category through the filter', async () => {
    await renderPage();

    fireEvent.change(screen.getByLabelText('Filter by category'), { target: { value: '1' } });

    await waitFor(() =>
      expect(getAllEntries).toHaveBeenLastCalledWith(
        expect.objectContaining({ categoryId: 1 })
      )
    );
  });
});
