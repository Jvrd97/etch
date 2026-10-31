// [review:need-review] PHASE-01/73-dashboard-hero-today-ring, #176, #76, #78, PHASE-03/252, PHASE-03/264
// summary: tests for useDashboard's hero load, bounded recent-activity feed and Trends - targeted day-window, last-written and recent queries; the hero never reads the history list; trends cost one table request per period and fail on their own
// summary: #264 — the trends range ends on the server's day (browser a day behind or ahead, server unreachable)
// summary: #252 — the hero counts today by the server day (browser a day behind or ahead), the window around the browser's day is cut to the server's two days, a day outside it is read exactly, and a server that cannot name its day leaves the browser's

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import type { Category, CategoryStreak, Entry, Field, JournalEntry, TableResponse } from '@/lib/api';
import { previousDay } from '@/lib/chart-utils';
import { todayISO } from '@/lib/date';
import { localNoonOf, shiftDay } from '@/lib/server-day';
import { trendDateRange } from '@/lib/trends';

const TIMESTAMP = '2026-07-24T09:00:00Z';

const GLASSES: Field = {
  id: 7,
  category_id: 1,
  name: 'Glasses',
  field_type: 'number',
  is_required: false,
  order: 1,
  created_at: TIMESTAMP,
  updated_at: TIMESTAMP,
};

const WATER: Category = {
  id: 1,
  name: 'Water',
  display_mode: 'form',
  streak_mode: 'build',
  is_active: true,
  created_at: TIMESTAMP,
  updated_at: TIMESTAMP,
  fields: [GLASSES],
};

const NO_SMOKING: Category = {
  ...WATER,
  id: 2,
  name: 'No Smoking',
  streak_mode: 'avoid',
};

const SMOKING_STREAK: CategoryStreak = {
  category_id: NO_SMOKING.id,
  streak_mode: 'avoid',
  current_streak: 12,
  best_streak: 12,
  last_relapse_date: null,
};

/** An entry as the API echoes it back. */
function entry(id: number, entryDate: string, amount: string): Entry {
  return {
    id,
    category_id: WATER.id,
    entry_date: entryDate,
    created_at: TIMESTAMP,
    updated_at: TIMESTAMP,
    values: [{ id, entry_id: id, field_id: GLASSES.id, value: amount }],
  };
}

interface EntriesQuery {
  categoryId?: number;
  skip?: number;
  startDate?: string;
  endDate?: string;
  limit?: number;
  sort?: string;
}

/** Every `GET /entries` the hook issued, in call order. */
let entriesCalls: EntriesQuery[];
/** Answer for the day-window query, keyed by nothing — the suite sets it per test. */
let dayWindow: Entry[];
let readDayMode: ReturnType<typeof mock>;
let lastWritten: Entry[];
let recentEntries: Entry[];
let journalItems: JournalEntry[];
/** Every `GET /journal` the hook issued, in call order. */
let journalCalls: unknown[];
/** The unbounded history list, which the hero must never read. */
let history: Entry[];
let categoryHistory: Entry[];
let getAllCategories: ReturnType<typeof mock>;
let getStreaksApi: ReturnType<typeof mock>;
let tableGet: ReturnType<typeof mock>;

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
    getById: () => Promise.resolve(null),
    getStreak: () => Promise.resolve(null),
    getStreaks: (mode: 'avoid' | 'build') => getStreaksApi(mode),
    create: () => Promise.resolve(null),
    update: () => Promise.resolve(null),
    delete: () => Promise.resolve(undefined),
  },
  // GET /table feeds the Trends block; the dashboard asks it once per period.
  tableAPI: {
    get: (dateFrom: string, dateTo: string) => tableGet(dateFrom, dateTo),
  },
  entriesAPI: {
    getAll: (params?: EntriesQuery) => {
      entriesCalls.push(params ?? {});
      if (params?.categoryId !== undefined) {
        const skip = params.skip ?? 0;
        return Promise.resolve(categoryHistory.slice(skip, skip + (params.limit ?? 100)));
      }
      if (params?.sort !== undefined && params.limit === 1) return Promise.resolve(lastWritten);
      if (params?.sort !== undefined) return Promise.resolve(recentEntries);
      if (params?.startDate !== undefined) return Promise.resolve(dayWindow);
      return Promise.resolve(history);
    },
    create: () => Promise.resolve(null),
    update: () => Promise.resolve(null),
    delete: () => Promise.resolve(undefined),
    upsertChecklist: () => Promise.resolve({}),
  },
  journalAPI: {
    getAll: (params?: unknown) => {
      journalCalls.push(params);
      return Promise.resolve({ items: journalItems, total: 4 });
    },
    getById: () => Promise.resolve(null),
    create: () => Promise.resolve(null),
  },
}));

const { useDashboard, DAY_WINDOW_LIMIT } = await import('./useDashboard');

function emptyTable(): TableResponse {
  return { categories: [], days: [] };
}

/** A table answer where Water has `amount` glasses on each of the given days. */
function waterTable(dates: string[], amount: string): TableResponse {
  return {
    categories: [],
    days: dates.map((date) => ({
      date,
      cells: [
        { category_id: WATER.id, field_id: GLASSES.id, aggregated_value: amount, entry_count: 1 },
      ],
    })),
  };
}

/** What `GET /day-mode` answers: the day the server is running. */
function dayModeOf(date: string) {
  return { date, kind: 'work', nocode: false, source: 'schedule' };
}

/** Today exactly as the hook computes it — the local calendar date, not the UTC one. */
const TODAY = todayISO();

beforeEach(() => {
  entriesCalls = [];
  dayWindow = [];
  lastWritten = [];
  recentEntries = [];
  journalItems = [];
  journalCalls = [];
  history = [];
  categoryHistory = [];
  getAllCategories = mock(() => Promise.resolve([WATER]));
  getStreaksApi = mock(() => Promise.resolve([]));
  readDayMode = mock(() => Promise.resolve(dayModeOf(TODAY)));
  tableGet = mock(() => Promise.resolve(emptyTable()));
});

afterEach(() => {
  cleanup();
});

describe('useDashboard hero', () => {
  it('loads a bounded recent feed and merges journal entries by creation time', async () => {
    recentEntries = [entry(2, TODAY, '250')];
    journalItems = [{
      id: 7,
      title: 'Day reflection',
      content: 'A note',
      entry_date: TODAY,
      created_at: '2026-07-24T10:00:00Z',
      updated_at: TIMESTAMP,
    }];

    const { result } = renderHook(() => useDashboard());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.recentActivity.map(({ kind }) => kind)).toEqual(['journal', 'entry']);
    expect(entriesCalls).toContainEqual({ sort: 'created_at_desc', limit: 5 });
    // One page of notes serves the total, the hero's journal date and the feed.
    expect(journalCalls).toEqual([{ limit: 5 }]);
  });

  it('counts the ring from the day window, ignoring the history list', async () => {
    dayWindow = [entry(1, TODAY, '2'), entry(2, TODAY, '3')];
    history = Array.from({ length: 40 }, (_, i) => entry(100 + i, '2026-01-01', '1'));

    const { result } = renderHook(() => useDashboard());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.hero.entriesToday).toBe(2);
    expect(result.current.hero.ringProgress).toBe(1);
  });

  it('asks the API for the last written entry instead of scanning the history', async () => {
    lastWritten = [entry(9, TODAY, '5')];
    history = [entry(500, '2026-01-01', '99')];

    const { result } = renderHook(() => useDashboard());
    await waitFor(() => expect(result.current.loading).toBe(false));

    const lastWrittenCall = entriesCalls.find((call) => call.sort !== undefined && call.limit === 1);
    expect(lastWrittenCall?.sort).toBe('created_at_desc');
    expect(lastWrittenCall?.limit).toBe(1);
    expect(result.current.hero.lastEntry?.entryId).toBe(9);
    expect(result.current.hero.lastEntry?.categoryName).toBe('Water');
    expect(result.current.hero.lastEntry?.value).toBe('5');
    expect(result.current.hero.lastEntry?.loggedAgo).toContain('Logged');
  });

  it('bounds the day query to yesterday and today, so a run can be judged', async () => {
    const { result } = renderHook(() => useDashboard());
    await waitFor(() => expect(result.current.loading).toBe(false));

    const dayCall = entriesCalls.find(
      (call) => call.startDate !== undefined && call.sort === undefined
    );
    // The window is stepped with the canonical calendar helper, not with hand
    // arithmetic on milliseconds: across a DST boundary `now - 24h` lands on
    // today or on the day before yesterday, and the run judgement goes with it.
    // It is read for the days around the browser's and cut to the server's two.
    expect(dayCall?.endDate).toBe(shiftDay(TODAY, 1));
    expect(dayCall?.startDate).toBe(shiftDay(TODAY, -2));
    expect(entriesCalls.filter((call) => call.startDate !== undefined && call.sort === undefined)).toHaveLength(1);
  });

  it('counts today by the server day when the browser is a day behind', async () => {
    const serverDay = shiftDay(TODAY, 1);
    readDayMode = mock(() => Promise.resolve(dayModeOf(serverDay)));
    dayWindow = [entry(1, TODAY, '1'), entry(2, serverDay, '2'), entry(3, serverDay, '3')];
    const { result } = renderHook(() => useDashboard());
    await waitFor(() => expect(result.current.loading).toBe(false));

    // The entry of the browser's day is yesterday for the server, not part of today.
    expect(result.current.hero.entriesToday).toBe(2);
  });

  it('counts today by the server day when the browser is a day ahead', async () => {
    const serverDay = shiftDay(TODAY, -1);
    readDayMode = mock(() => Promise.resolve(dayModeOf(serverDay)));
    dayWindow = [entry(1, TODAY, '1'), entry(2, serverDay, '2')];
    const { result } = renderHook(() => useDashboard());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.hero.entriesToday).toBe(1);
  });

  it('asks the day exactly when the server day is outside the window', async () => {
    const farDay = shiftDay(TODAY, 30);
    readDayMode = mock(() => Promise.resolve(dayModeOf(farDay)));
    dayWindow = [entry(1, farDay, '1')];
    const { result } = renderHook(() => useDashboard());
    await waitFor(() => expect(result.current.loading).toBe(false));

    const dayCalls = entriesCalls.filter((call) => call.startDate !== undefined && call.sort === undefined);
    expect(dayCalls.at(-1)).toMatchObject({ startDate: previousDay(farDay), endDate: farDay });
    expect(result.current.hero.entriesToday).toBe(1);
  });

  it('reads the two days exactly when the window came back full', async () => {
    const full = Array.from({ length: DAY_WINDOW_LIMIT }, (_, index) => entry(500 + index, TODAY, '1'));
    dayWindow = full;
    entriesCalls = [];
    let reads = 0;
    const { result } = renderHook(() => useDashboard());
    await waitFor(() => expect(result.current.loading).toBe(false));
    reads = entriesCalls.filter((call) => call.startDate !== undefined && call.sort === undefined).length;

    // The full window is not trusted: the exact two days are read once more.
    expect(reads).toBe(2);
    expect(entriesCalls.filter((call) => call.startDate !== undefined).at(-1)).toMatchObject({
      startDate: previousDay(TODAY),
      endDate: TODAY,
    });
  });

  it('keeps the browser day when the server cannot name its own', async () => {
    readDayMode = mock(() => Promise.reject(new Error('offline')));
    dayWindow = [entry(1, TODAY, '1')];
    const { result } = renderHook(() => useDashboard());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.hero.entriesToday).toBe(1);
    expect(result.current.error).toBeNull();
  });

  it('bounds the day query with an explicit limit, not the server default', async () => {
    const { result } = renderHook(() => useDashboard());
    await waitFor(() => expect(result.current.loading).toBe(false));

    const dayCall = entriesCalls.find(
      (call) => call.startDate !== undefined && call.sort === undefined
    );
    expect(dayCall?.limit).toBeGreaterThan(0);
  });

  it('leaves the hero empty and readable when the day holds nothing', async () => {
    const { result } = renderHook(() => useDashboard());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.hero.entriesToday).toBe(0);
    expect(result.current.hero.lastEntry).toBeNull();
    expect(result.current.hero.tip.text.length).toBeGreaterThan(0);
  });

  it('loads only the last written entry per Continue tracking category', async () => {
    categoryHistory = Array.from({ length: 101 }, (_, i) => entry(i + 1, TODAY, String(i)));
    const { result } = renderHook(() => useDashboard());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.continueEntries).toEqual([categoryHistory[0]]);
    const categoryCalls = entriesCalls.filter((call) => call.categoryId === WATER.id);
    expect(categoryCalls).toHaveLength(1);
    expect(categoryCalls[0].limit).toBe(1);
    expect(categoryCalls[0].skip).toBeUndefined();
    expect(categoryCalls[0].sort).toBe('created_at_desc');
  });

  it('loads avoid streaks once and pairs them with active categories', async () => {
    getAllCategories = mock(() => Promise.resolve([WATER, NO_SMOKING]));
    getStreaksApi = mock(() => Promise.resolve([SMOKING_STREAK]));

    const { result } = renderHook(() => useDashboard());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(getStreaksApi).toHaveBeenCalledWith('avoid');
    expect(result.current.avoidStreaks).toEqual([
      { category: NO_SMOKING, streak: SMOKING_STREAK },
    ]);
  });
});

describe('useDashboard trends', () => {
  it('builds the rows from one table request that covers the period and the one before', async () => {
    tableGet = mock(() => Promise.resolve(waterTable([TODAY], '6')));

    const { result } = renderHook(() => useDashboard());
    await waitFor(() => expect(result.current.trendState.status).toBe('ready'));

    const { dateFrom, dateTo } = trendDateRange(30, localNoonOf(TODAY));
    expect(tableGet).toHaveBeenCalledTimes(1);
    expect(tableGet).toHaveBeenCalledWith(dateFrom, dateTo);
    expect(result.current.trendPeriod).toBe(30);
    const state = result.current.trendState;
    expect(state.status === 'ready' && state.trends.map((trend) => trend.categoryId)).toEqual([
      WATER.id,
    ]);
  });

  it('ends the range on the server day when the browser is a day behind, and asks the table once', async () => {
    const serverDay = shiftDay(TODAY, 1);
    readDayMode = mock(() => Promise.resolve(dayModeOf(serverDay)));
    tableGet = mock(() => Promise.resolve(waterTable([serverDay], '6')));

    const { result } = renderHook(() => useDashboard());
    await waitFor(() => expect(result.current.trendState.status).toBe('ready'));

    const { dateFrom, dateTo } = trendDateRange(30, localNoonOf(serverDay));
    expect(dateTo).toBe(serverDay);
    expect(tableGet).toHaveBeenCalledTimes(1);
    expect(tableGet).toHaveBeenCalledWith(dateFrom, dateTo);
    const state = result.current.trendState;
    expect(state.status === 'ready' && state.trends[0]?.sparkline.at(-1)?.value).toBe(6);
  });

  it('ends the range on the server day when the browser is a day ahead', async () => {
    const serverDay = shiftDay(TODAY, -1);
    readDayMode = mock(() => Promise.resolve(dayModeOf(serverDay)));

    const { result } = renderHook(() => useDashboard());
    await waitFor(() => expect(result.current.trendState.status).toBe('ready'));

    expect(tableGet).toHaveBeenCalledWith(
      trendDateRange(30, localNoonOf(serverDay)).dateFrom,
      serverDay
    );
  });

  it('keeps the browser day for the range when the server cannot name its day', async () => {
    readDayMode = mock(() => Promise.reject(new Error('offline')));

    const { result } = renderHook(() => useDashboard());
    await waitFor(() => expect(result.current.trendState.status).toBe('ready'));

    expect(tableGet).toHaveBeenCalledWith(trendDateRange(30, localNoonOf(TODAY)).dateFrom, trendDateRange(30, localNoonOf(TODAY)).dateTo);
  });

  it('stays loading until the dashboard has its categories, then asks once', async () => {
    const { result } = renderHook(() => useDashboard());
    expect(result.current.trendState.status).toBe('loading');
    await waitFor(() => expect(result.current.trendState.status).toBe('ready'));
    expect(tableGet).toHaveBeenCalledTimes(1);
  });

  it('refetches only the table when the period changes', async () => {
    tableGet = mock(() => Promise.resolve(waterTable([TODAY], '6')));
    const { result } = renderHook(() => useDashboard());
    await waitFor(() => expect(result.current.trendState.status).toBe('ready'));
    const categoryLoads = getAllCategories.mock.calls.length;

    act(() => result.current.setTrendPeriod(7));
    await waitFor(() => expect(tableGet).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(result.current.trendState.status).toBe('ready'));

    const { dateFrom, dateTo } = trendDateRange(7, localNoonOf(TODAY));
    expect(tableGet).toHaveBeenLastCalledWith(dateFrom, dateTo);
    expect(result.current.trendPeriod).toBe(7);
    expect(getAllCategories.mock.calls.length).toBe(categoryLoads);
  });

  it('ignores choosing the period that is already shown', async () => {
    const { result } = renderHook(() => useDashboard());
    await waitFor(() => expect(result.current.trendState.status).toBe('ready'));

    act(() => result.current.setTrendPeriod(30));

    expect(result.current.trendState.status).toBe('ready');
    expect(tableGet).toHaveBeenCalledTimes(1);
  });

  it('shows loading while the new period is on its way', async () => {
    const { result } = renderHook(() => useDashboard());
    await waitFor(() => expect(result.current.trendState.status).toBe('ready'));

    tableGet = mock(() => new Promise<TableResponse>(() => {}));
    act(() => result.current.setTrendPeriod(90));

    expect(result.current.trendState.status).toBe('loading');
  });

  it('drops the answer of a period the user has already left', async () => {
    let answerFirst: (table: TableResponse) => void = () => {};
    tableGet = mock((dateFrom: string) =>
      dateFrom === trendDateRange(30, localNoonOf(TODAY)).dateFrom
        ? new Promise<TableResponse>((resolve) => {
            answerFirst = resolve;
          })
        : Promise.resolve(waterTable([TODAY], '2'))
    );
    const { result } = renderHook(() => useDashboard());
    await waitFor(() => expect(tableGet).toHaveBeenCalledTimes(1));

    act(() => result.current.setTrendPeriod(7));
    await waitFor(() => expect(result.current.trendState.status).toBe('ready'));
    await act(async () => answerFirst(waterTable([TODAY], '999')));

    const state = result.current.trendState;
    expect(state.status === 'ready' && state.trends[0]?.average).toBe(2);
  });

  it('keeps the rest of the dashboard when the table request fails', async () => {
    tableGet = mock(() => Promise.reject(new Error('table is down')));

    const { result } = renderHook(() => useDashboard());
    await waitFor(() => expect(result.current.trendState.status).toBe('error'));

    expect(result.current.trendState).toEqual({ status: 'error', message: 'table is down' });
    expect(result.current.error).toBeNull();
    expect(result.current.loading).toBe(false);
  });

  it('leaves the table alone when there are no categories to trend', async () => {
    getAllCategories = mock(() => Promise.resolve([]));

    const { result } = renderHook(() => useDashboard());
    await waitFor(() => expect(result.current.trendState.status).toBe('ready'));

    expect(tableGet).not.toHaveBeenCalled();
    expect(result.current.trendState).toEqual({ status: 'ready', trends: [] });
  });
});
