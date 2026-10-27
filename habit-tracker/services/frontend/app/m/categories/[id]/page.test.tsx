// [review:need-review] PHASE-01/42-mobile-categories-and-detail, PHASE-01/207, PHASE-03/252
// summary: integration tests for /m/categories/[id] — the tab strip that scrolls inside itself instead of widening the page, mobile-side links, the relapse block of an avoid category with the server's relapse days, and the shared EntryEditorSheet locked to this category
// summary: #252 — quick-add on the mobile category page files the entry under the server's day

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { Category, Entry, Field, RelapseHistory } from '@/lib/api';

const TIMESTAMP = '2026-07-24T00:00:00Z';
const TODAY = '2026-07-24';
const SERVER_DAY = '2026-07-25';

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

const AVOID_CATEGORY: Category = { ...CATEGORY, streak_mode: 'avoid' };
const OTHER_CATEGORY: Category = { ...CATEGORY, id: 2, name: 'Mood', fields: [] };

const STREAK: RelapseHistory = {
  category_id: 1,
  streak_mode: 'avoid',
  current_streak: 3,
  best_streak: 9,
  last_relapse_date: '2026-07-21',
  tracked_since: '2026-07-01',
  relapse_dates: ['2026-07-12', '2026-07-21'],
  today: '2026-10-25',
};

const ENTRY: Entry = {
  id: 10,
  category_id: 1,
  entry_date: TODAY,
  created_at: TIMESTAMP,
  updated_at: TIMESTAMP,
  values: [{ id: 1, entry_id: 10, field_id: 7, value: '8' }],
};

let params: Record<string, string>;
let getCategory: ReturnType<typeof mock>;
let getAllCategories: ReturnType<typeof mock>;
let getRelapses: ReturnType<typeof mock>;
let getTable: ReturnType<typeof mock>;
let getAllEntries: ReturnType<typeof mock>;
let createEntry: ReturnType<typeof mock>;

// Same process-wide replacement rule as the API mock: the hooks other suites
// import have to stay present even though this screen only reads the route params.
mock.module('next/navigation', () => ({
  useParams: () => params,
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => `/m/categories/${params.id}`,
  useRouter: () => ({ push: () => {}, replace: () => {} }),
}));

// Declares the whole surface on purpose: bun fixes a module's export *names* the
// first time anything links against it and shares that registry across the run,
// so a partial mock here would delete members other suites reach for.
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
    getById: (id: number) => getCategory(id),
    getAll: () => getAllCategories(),
    getStreak: () => Promise.resolve(null),
    getRelapses: (id: number) => getRelapses(id),
    recordRelapse: () => Promise.resolve(ENTRY),
    create: () => Promise.resolve(CATEGORY),
    update: () => Promise.resolve(CATEGORY),
    delete: () => Promise.resolve(undefined),
  },
  entriesAPI: {
    getAll: (query?: unknown) => getAllEntries(query),
    create: (data: unknown) => createEntry(data),
    update: () => Promise.resolve(ENTRY),
    delete: () => Promise.resolve(undefined),
    upsertChecklist: () => Promise.resolve({}),
  },
  tableAPI: { get: (from: string, to: string) => getTable(from, to) },
}));

// The chart is recharts inside a ResponsiveContainer, which measures a real
// layout; this screen's contract here is the page around it.
mock.module('@/components/CategoryChart', () => ({
  default: () => <div data-testid="category-chart" />,
}));

const { default: MobileCategoryDetailPage } = await import('./page');

async function renderPage() {
  render(<MobileCategoryDetailPage />);
  await waitFor(() => expect(screen.getByTestId('category-chart')).toBeDefined());
}

let readDayMode: ReturnType<typeof mock>;

beforeEach(() => {
  // The server runs the day after the one the browser (and the fixtures) name.
  readDayMode = mock(() => Promise.resolve({ date: SERVER_DAY, kind: 'work', nocode: false, source: 'schedule' }));
  params = { id: '1' };
  getCategory = mock(() => Promise.resolve(CATEGORY));
  getAllCategories = mock(() => Promise.resolve([CATEGORY, OTHER_CATEGORY]));
  getRelapses = mock(() => Promise.resolve(STREAK));
  getTable = mock(() => Promise.resolve({ days: [] }));
  getAllEntries = mock(() => Promise.resolve([ENTRY]));
  createEntry = mock(() => Promise.resolve(ENTRY));
});

afterEach(() => {
  cleanup();
});

describe('/m/categories/[id]', () => {
  it('keeps the user inside the mobile shell when going back to the list', async () => {
    await renderPage();

    expect(screen.getByRole('link', { name: 'Categories' }).getAttribute('href')).toBe(
      '/m/categories'
    );
  });

  it('scrolls the tab strip inside itself rather than widening the page', async () => {
    await renderPage();

    const strip = screen.getByRole('navigation', { name: 'Categories' });
    // The strip is the one element that can outgrow a phone screen. Letting it
    // do so gives the whole body a horizontal scrollbar.
    expect(strip.className).toContain('overflow-x-auto');
    for (const link of Array.from(strip.querySelectorAll('a'))) {
      // Wrapping the pills instead would make the strip taller on every render;
      // they stay on one line and the strip scrolls.
      expect(link.className).toContain('whitespace-nowrap');
    }
  });

  it('points the tab strip at the mobile detail screens', async () => {
    await renderPage();

    const strip = screen.getByRole('navigation', { name: 'Categories' });
    expect(Array.from(strip.querySelectorAll('a')).map((a) => a.getAttribute('href'))).toEqual([
      '/m/categories/1',
      '/m/categories/2',
    ]);
  });

  it('marks the current category in the strip', async () => {
    await renderPage();

    const current = screen.getByRole('link', { name: 'Sleep', current: 'page' });
    expect(current.getAttribute('href')).toBe('/m/categories/1');
  });

  it('pages to the neighbouring category without leaving the mobile shell', async () => {
    params = { id: '2' };
    getCategory = mock(() => Promise.resolve(OTHER_CATEGORY));
    await renderPage();

    expect(
      screen.getByRole('link', { name: /Previous category/ }).getAttribute('href')
    ).toBe('/m/categories/1');
  });

  it('shows the relapse block with the days the server counted for an avoid category', async () => {
    getCategory = mock(() => Promise.resolve(AVOID_CATEGORY));
    await renderPage();

    expect(screen.getByRole('heading', { name: 'Срывы' })).toBeDefined();
    expect(getRelapses).toHaveBeenCalledWith(1);
    const list = screen.getByRole('list', { name: 'Последние срывы' });
    expect(Array.from(list.querySelectorAll('li')).map((item) => item.textContent)).toEqual([
      '21 июл 2026, Вт',
      '12 июл 2026, Вс',
    ]);
  });

  it('leaves the relapse block out for a build category', async () => {
    await renderPage();

    expect(screen.queryByRole('heading', { name: 'Срывы' })).toBeNull();
  });

  it('logs an entry into this category from the sheet', async () => {
    await renderPage();

    fireEvent.click(screen.getByRole('button', { name: 'New entry' }));
    fireEvent.change(screen.getByLabelText(/^Hours/), { target: { value: '8' } });
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));

    await waitFor(() => expect(createEntry).toHaveBeenCalled());
    // The category is fixed by the route: the sheet offers no picker to get it
    // wrong with.
    expect(createEntry.mock.calls[0][0]).toMatchObject({ category_id: 1 });
    expect(screen.queryByLabelText('Category')).toBeNull();
  });

  it('files the entry under the server day, not the browser one', async () => {
    await renderPage();

    fireEvent.click(screen.getByRole('button', { name: 'New entry' }));
    await waitFor(() =>
      expect((document.getElementById('entry-date') as HTMLInputElement).value).toBe(SERVER_DAY)
    );
    fireEvent.change(screen.getByLabelText(/^Hours/), { target: { value: '8' } });
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));

    await waitFor(() => expect(createEntry).toHaveBeenCalled());
    expect(createEntry.mock.calls[0][0]).toMatchObject({ entry_date: SERVER_DAY });
  });

  it('refetches the history once an entry was logged', async () => {
    await renderPage();
    const loadsBefore = getAllEntries.mock.calls.length;

    fireEvent.click(screen.getByRole('button', { name: 'New entry' }));
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));

    await waitFor(() =>
      expect(getAllEntries.mock.calls.length).toBeGreaterThan(loadsBefore)
    );
  });

  it('reports a route that carries something other than a category id', async () => {
    params = { id: 'nope' };
    render(<MobileCategoryDetailPage />);

    await waitFor(() => expect(screen.getByText('Invalid category id')).toBeDefined());
    expect(getCategory).not.toHaveBeenCalled();
  });

  it('says so when the category has no entries yet', async () => {
    getAllEntries = mock(() => Promise.resolve([]));
    await renderPage();

    expect(screen.getByText('No entries yet')).toBeDefined();
  });
});
