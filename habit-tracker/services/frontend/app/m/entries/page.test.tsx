// [review:need-review] PHASE-01/41-mobile-entries-fullscreen-sheet, PHASE-01/42-mobile-categories-and-detail, #176, #76, PHASE-03/252
// summary: mobile Entries tests cover the merged feed, category chips and editor sheet flows
// summary: #252 — a new entry is filed under the server's day (browser a day behind), follows it when it lands after a ?new=1 sheet is open, and keeps a date the reader picked

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import type { Category, Entry, Field } from '@/lib/api';

const TIMESTAMP = '2026-07-24T00:00:00Z';
const TODAY = '2026-07-24';
/** The day the server runs while the browser still says `TODAY`. */
const SERVER_DAY = '2026-07-25';

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
const WATER: Category = { ...CATEGORY, id: 2, name: 'Water', fields: [] };

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
  // Профили потолка и долг за переработку (#179): экран дня читает предложение,
  // экран недели — гроссбух. Заглушка стоит в каждом моке api, потому что bun
  // фиксирует имена экспортов модуля при первой линковке.
  profilesAPI: {
    proposal: () => Promise.resolve(null),
    activate: () => Promise.resolve(null),
    decline: () => Promise.resolve(null),
    debt: () => Promise.resolve({ open_minutes: 0, debts: [] }),
  },
  // Активность агента (#158, #160): экран дня читает её ради блока «где прошёл
  // день», а bun фиксирует имена экспортов модуля при первой линковке — мок,
  // забывший экспорт, удаляет его для всех, кто линкуется следом.
  agentAPI: {
    day: () => Promise.resolve(null),
    patchInterval: () => Promise.resolve(null),
    addManualInterval: () => Promise.resolve(null),
    titleRules: () => Promise.resolve([]),
    addTitleRule: () => Promise.resolve([]),
    patchTitleRule: () => Promise.resolve([]),
    deleteTitleRule: () => Promise.resolve([]),
    reorderTitleRules: () => Promise.resolve([]),
    settings: () => Promise.resolve({ titles_enabled: true, sampling_seconds: 5 }),
    saveSettings: () => Promise.resolve({ titles_enabled: true, sampling_seconds: 5 }),
    dayMode: () => readDayMode(),
  },
  // Справочник ролей (#140): экран дня читает его ради двух необязательных
  // полей у пункта плана. Заглушка стоит в каждом моке api по той же причине,
  // что и остальная поверхность: bun фиксирует имена экспортов модуля при
  // первой линковке, и мок, забывший экспорт, удаляет его для всех, кто
  // линкуется следом.
  rolesAPI: {
    listRoles: () => Promise.resolve([]),
    day: () => Promise.resolve(null),
    addTimeBlock: () => Promise.resolve(null),
    deleteTimeBlock: () => Promise.resolve({}),
    addAct: () => Promise.resolve(null),
    deleteAct: () => Promise.resolve({}),
  },
  // Правила дня (#152). Есть в каждом моке api по той же причине, что и
  // остальная поверхность: bun фиксирует имена экспортов модуля при первой
  // линковке, и мок, забывший экспорт, удаляет его для всех, кто линкуется следом.
  dayRulesAPI: {
    getHistory: () => Promise.resolve(null),
    getCurrent: () => Promise.resolve(null),
    publish: () => Promise.resolve(null),
  },
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
  // The Today screen carries the challenge block (#127). Present in every api
  // mock for the same reason the rest of the surface is: bun fixes a module's
  // export names on first link, so a mock that omits it deletes it for whoever
  // runs next.
  challengesAPI: {
    list: () => Promise.resolve([]),
    get: () => Promise.resolve(null),
    create: () => Promise.resolve(null),
    patch: () => Promise.resolve(null),
    recompute: () => Promise.resolve(null),
  },
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
  // The Entries feed merges journal notes (#76); declared here so the page does
  // not depend on another file having linked the export first.
  journalAPI: {
    getAll: () => Promise.resolve({ items: [], total: 0 }),
    getById: () => Promise.resolve(null),
    create: () => Promise.resolve(null),
  },
  tableAPI: { get: () => Promise.resolve({ days: [] }) },
}));

// Copied before mocking: bun rewrites a mocked module's namespace in place, and
// the feed reads the rest of `@/lib/date` (fromISODate) through the same mock.
const realDate = { ...(await import('@/lib/date')) };
mock.module('@/lib/date', () => ({ ...realDate, todayISO: () => TODAY }));

const { default: MobileEntriesPage } = await import('./page');
const { NEW_ENTRY_SHEET_TITLE } = await import('@/lib/ui-constants');

/** Render the screen and wait for the first load to settle. */
async function renderPage() {
  render(<MobileEntriesPage />);
  await waitFor(() => expect(screen.getByRole('heading', { name: 'Sleep' })).toBeDefined());
}

let readDayMode: ReturnType<typeof mock>;

beforeEach(() => {
  readDayMode = mock(() => Promise.resolve({ date: TODAY, kind: 'work', nocode: false, source: 'schedule' }));
  searchParams = new URLSearchParams();
  getAllCategories = mock(() => Promise.resolve([CATEGORY, WATER]));
  getAllEntries = mock(() => Promise.resolve([ENTRY]));
  createEntry = mock(() => Promise.resolve(ENTRY));
  updateEntry = mock(() => Promise.resolve(ENTRY));
  deleteEntry = mock(() => Promise.resolve());
});

afterEach(() => {
  cleanup();
});

it('prefills the category carried by a new-entry deep link', async () => {
  searchParams = new URLSearchParams('new=1&category=2');
  await renderPage();
  expect((screen.getByLabelText('Category') as HTMLSelectElement).value).toBe('2');
});

describe('/m/entries day', () => {
  it('files a new entry under the server day while the browser is a day behind', async () => {
    readDayMode = mock(() =>
      Promise.resolve({ date: SERVER_DAY, kind: 'work', nocode: false, source: 'schedule' })
    );
    await renderPage();

    fireEvent.click(screen.getByRole('button', { name: 'New entry' }));
    await waitFor(() =>
      expect((document.getElementById('entry-date') as HTMLInputElement).value).toBe(SERVER_DAY)
    );
    fireEvent.change(screen.getByLabelText('Hours'), { target: { value: '9' } });
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));

    await waitFor(() => expect(createEntry).toHaveBeenCalledTimes(1));
    expect(createEntry.mock.calls[0][0]).toMatchObject({ entry_date: SERVER_DAY });
  });

  it('follows the server day when it lands after a ?new=1 sheet is already open', async () => {
    searchParams = new URLSearchParams('new=1');
    let release!: (mode: unknown) => void;
    const pendingDay = new Promise((resolve) => { release = resolve; });
    readDayMode = mock(() => pendingDay);
    render(<MobileEntriesPage />);
    await waitFor(() => expect(screen.getByRole('dialog')).toBeDefined());
    expect((document.getElementById('entry-date') as HTMLInputElement).value).toBe(TODAY);

    release({ date: SERVER_DAY, kind: 'work', nocode: false, source: 'schedule' });

    await waitFor(() =>
      expect((document.getElementById('entry-date') as HTMLInputElement).value).toBe(SERVER_DAY)
    );
  });

  it('keeps the date the reader picked when the server day lands', async () => {
    searchParams = new URLSearchParams('new=1');
    let release!: (mode: unknown) => void;
    const pendingDay = new Promise((resolve) => { release = resolve; });
    readDayMode = mock(() => pendingDay);
    render(<MobileEntriesPage />);
    await waitFor(() => expect(screen.getByRole('dialog')).toBeDefined());
    fireEvent.change(document.getElementById('entry-date') as HTMLInputElement, {
      target: { value: '2026-07-01' },
    });

    release({ date: SERVER_DAY, kind: 'work', nocode: false, source: 'schedule' });
    await waitFor(() => expect(readDayMode).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect((document.getElementById('entry-date') as HTMLInputElement).value).toBe('2026-07-01');
  });
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

    fireEvent.click(within(screen.getByRole('group', { name: 'Filter by category' })).getByRole('button', { name: 'Sleep' }));

    await waitFor(() =>
      expect(getAllEntries).toHaveBeenLastCalledWith(
        expect.objectContaining({ categoryId: 1 })
      )
    );

    fireEvent.click(within(screen.getByRole('group', { name: 'Filter by category' })).getByRole('button', { name: 'All' }));
    await waitFor(() =>
      expect(getAllEntries).toHaveBeenLastCalledWith(
        expect.objectContaining({ categoryId: undefined })
      )
    );
  });
});
