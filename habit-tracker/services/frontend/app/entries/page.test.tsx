// [review:need-review] PHASE-01/41-mobile-entries-fullscreen-sheet, PHASE-01/42-mobile-categories-and-detail
// summary: characterization tests for the desktop /entries page, pinning its behaviour across the move onto useEntries

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
  created_at: TIMESTAMP,
  updated_at: TIMESTAMP,
  values: [{ id: 1, entry_id: 10, field_id: 7, value: '8' }],
};

let getAllEntries: ReturnType<typeof mock>;
let createEntry: ReturnType<typeof mock>;
let searchParams: URLSearchParams;

// The whole module is replaced process-wide, so the members other suites reach
// for have to stay present even though this one never calls them.
mock.module('@/lib/api', () => ({
  // The goal board's client (#93). Present in every api mock for the same
  // reason the rest of the surface is: bun fixes a module's export names on
  // first link, so a mock that omits it deletes it for whoever runs next.
  goalsAPI: {
    get: () => Promise.resolve(null),
    patchMilestone: () => Promise.resolve(null),
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
    getAll: () => Promise.resolve([CATEGORY]),
    getById: () => Promise.resolve(CATEGORY),
    getStreak: () => Promise.resolve(null),
    create: () => Promise.resolve(CATEGORY),
    update: () => Promise.resolve(CATEGORY),
    delete: () => Promise.resolve(),
  },
  entriesAPI: {
    getAll: (params?: unknown) => getAllEntries(params),
    create: (data: unknown) => createEntry(data),
    update: () => Promise.resolve(ENTRY),
    delete: () => Promise.resolve(),
    upsertChecklist: () => Promise.resolve({}),
  },
  tableAPI: { get: () => Promise.resolve({ days: [] }) },
}));

// Same process-wide replacement rule as the API mock: the hooks other suites
// import have to stay present even though this screen only reads the query.
mock.module('next/navigation', () => ({
  useSearchParams: () => searchParams,
  useParams: () => ({}),
  usePathname: () => '/entries',
  useRouter: () => ({ push: () => {}, replace: () => {} }),
}));

mock.module('@/lib/date', () => ({ todayISO: () => TODAY }));

const { default: EntriesPage } = await import('./page');

beforeEach(() => {
  searchParams = new URLSearchParams();
  getAllEntries = mock(() => Promise.resolve([ENTRY]));
  createEntry = mock(() => Promise.resolve(ENTRY));
});

afterEach(() => {
  cleanup();
});

describe('/entries (desktop)', () => {
  it('lists the entries grouped by date', async () => {
    render(<EntriesPage />);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Sleep' })).toBeDefined());
    expect(screen.getByText(TODAY)).toBeDefined();
  });

  it('opens the form straight away with ?new=1', async () => {
    searchParams = new URLSearchParams('new=1');
    render(<EntriesPage />);

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'New entry' })).toBeDefined()
    );
  });

  it('creates an entry from the form and reloads the list', async () => {
    render(<EntriesPage />);
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Sleep' })).toBeDefined());
    const loadsBefore = getAllEntries.mock.calls.length;

    fireEvent.click(screen.getByLabelText('New entry'));
    fireEvent.click(screen.getByRole('button', { name: 'Create entry' }));

    await waitFor(() => expect(createEntry).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(getAllEntries.mock.calls.length).toBeGreaterThan(loadsBefore)
    );
  });

  it('refetches with the selected category filter', async () => {
    render(<EntriesPage />);
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Sleep' })).toBeDefined());

    fireEvent.change(screen.getByLabelText('Filter by category'), { target: { value: '1' } });

    await waitFor(() =>
      expect(getAllEntries).toHaveBeenLastCalledWith(
        expect.objectContaining({ categoryId: 1 })
      )
    );
  });
});
