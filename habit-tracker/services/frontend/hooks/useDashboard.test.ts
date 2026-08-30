// [review:need-review] PHASE-01/73-dashboard-hero-today-ring
// summary: tests for useDashboard's hero load — the day window and the last-written lookup are targeted queries, and the hero never reads the history list

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, renderHook, waitFor } from '@testing-library/react';
import type { Category, Entry, Field } from '@/lib/api';
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
/** The unbounded history list, which the hero must never read. */
let history: Entry[];

mock.module('@/lib/api', () => ({
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
    getAll: () => Promise.resolve([WATER]),
    getById: () => Promise.resolve(null),
    getStreak: () => Promise.resolve(null),
    create: () => Promise.resolve(null),
    update: () => Promise.resolve(null),
    delete: () => Promise.resolve(undefined),
  },
  entriesAPI: {
    getAll: (params?: EntriesQuery) => {
      entriesCalls.push(params ?? {});
      if (params?.sort !== undefined) return Promise.resolve(lastWritten);
      if (params?.startDate !== undefined) return Promise.resolve(dayWindow);
      return Promise.resolve(history);
    },
    create: () => Promise.resolve(null),
    update: () => Promise.resolve(null),
    delete: () => Promise.resolve(undefined),
    upsertChecklist: () => Promise.resolve({}),
  },
  journalAPI: {
    getAll: () => Promise.resolve({ items: [], total: 4 }),
    getById: () => Promise.resolve(null),
    create: () => Promise.resolve(null),
  },
  tableAPI: { get: () => Promise.resolve({ days: [] }) },
}));

const { useDashboard } = await import('./useDashboard');

/** Today exactly as the hook computes it — the local calendar date, not the UTC one. */
const TODAY = todayISO();

beforeEach(() => {
  entriesCalls = [];
  dayWindow = [];
  lastWritten = [];
  history = [];
});

afterEach(() => {
  cleanup();
});

describe('useDashboard hero', () => {
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

    const lastWrittenCall = entriesCalls.find((call) => call.sort !== undefined);
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
});
