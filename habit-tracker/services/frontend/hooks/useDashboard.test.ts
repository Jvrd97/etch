// [review:need-review] PHASE-01/73-dashboard-hero-today-ring, #176, #76
// summary: tests for useDashboard's hero load and bounded recent-activity feed — targeted day-window, last-written and recent queries; the hero never reads the history list

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, renderHook, waitFor } from '@testing-library/react';
import type { Category, CategoryStreak, Entry, Field, JournalEntry } from '@/lib/api';
import { previousDay } from '@/lib/chart-utils';
import { todayISO } from '@/lib/date';

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

const { useDashboard } = await import('./useDashboard');

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
    expect(dayCall?.endDate).toBe(TODAY);
    expect(dayCall?.startDate).toBe(previousDay(TODAY));
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
