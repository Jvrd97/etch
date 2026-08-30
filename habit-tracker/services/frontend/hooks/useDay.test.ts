// [review:need-review] PHASE-03/86, PHASE-03/88, PHASE-03/90
// summary: tests for useDay — a null date asks the server for today instead of reading the browser calendar, a named date is passed through, a failure clears the stale day, reload re-fetches, and only an explicit flag claims a person opened the day (whether the server honours it is the server's call since #90)

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import type { DayDetail } from '@/lib/api';

const DAY: DayDetail = {
  day: {
    date: '2026-08-30',
    kind: 'off',
    is_nocode: false,
    opened_at: null,
    last_touched_at: null,
  },
  rule: {
    id: 2,
    valid_from: '2026-08-17',
    valid_to: null,
    timezone: 'Europe/Berlin',
    day_start_hour: 4,
    work_cap_min: 480,
    work_hard_cap_min: 540,
    work_stop_at: '16:00:00',
    max_work_tasks: 4,
    tasks_required_ratio: '1.00',
    overtime_disqualifies: true,
    workdays: [1, 2, 3, 4, 5],
    nocode_days: [2, 4],
    required_anchors: ['подъём'],
    note_md: '',
  },
  plan: null,
  has_plan: false,
  marks: [],
  task_counts: { planned: 0, done: 0, failed: 0, skipped: 0, pending: 0 },
  notebook: null,
  summary: {
    day_date: '2026-08-30',
    closed: false,
    rule_set_id: 2,
    verdict: null,
    verdict_reason: 'not_closed',
    verdict_override: false,
    verdict_override_note: null,
    anchors_done: 0,
    anchors_total: 0,
    tasks_done: 0,
    tasks_total: 0,
    work_minutes: null,
    streak_after: null,
    wrote_from_scratch: null,
    education_debt: null,
    reviewed_today: null,
    body_md: '',
    missing_data: ['work_minutes'],
    missing_anchors: [],
    source: 'close',
  },
};

let getToday: ReturnType<typeof mock>;
let getDay: ReturnType<typeof mock>;
let openToday: ReturnType<typeof mock>;
let openDay: ReturnType<typeof mock>;

// Declares the whole surface on purpose: bun fixes a module's export *names*
// the first time anything links against it and shares that registry across the
// run, so a partial mock here would delete members other suites reach for.
mock.module('@/lib/api', () => ({
  // The goal board's client (#93). Present in every api mock for the same
  // reason the rest of the surface is: bun fixes a module's export names on
  // first link, so a mock that omits it deletes it for whoever runs next.
  goalsAPI: {
    get: () => Promise.resolve(null),
    patchMilestone: () => Promise.resolve(null),
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
    getAll: () => Promise.resolve([]),
    getById: () => Promise.resolve(null),
    getStreak: () => Promise.resolve(null),
    create: () => Promise.resolve(null),
    update: () => Promise.resolve(null),
    delete: () => Promise.resolve(undefined),
  },
  entriesAPI: {
    getAll: () => Promise.resolve([]),
    create: () => Promise.resolve(null),
    update: () => Promise.resolve(null),
    delete: () => Promise.resolve(undefined),
    upsertChecklist: () => Promise.resolve({}),
  },
  journalAPI: {
    getAll: () => Promise.resolve({ items: [], total: 0 }),
    getById: () => Promise.resolve(null),
    create: () => Promise.resolve(null),
  },
  tableAPI: { get: () => Promise.resolve({ days: [] }) },
  dayAPI: {
    getToday: () => getToday(),
    get: (date: string) => getDay(date),
    openToday: () => openToday(),
    open: (date: string) => openDay(date),
  },
}));

const { useDay } = await import('./useDay');

beforeEach(() => {
  getToday = mock(() => Promise.resolve(DAY));
  getDay = mock(() => Promise.resolve(DAY));
  openToday = mock(() => Promise.resolve(DAY));
  openDay = mock(() => Promise.resolve(DAY));
});

afterEach(() => {
  cleanup();
});

describe('useDay', () => {
  it('asks the server which day today is when no date is given', async () => {
    // Not `new Date()`: the day runs from 04:00, so between midnight and four
    // the browser calendar names a day nothing else is writing into.
    const { result } = renderHook(() => useDay(null));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(getToday).toHaveBeenCalled();
    expect(getDay).not.toHaveBeenCalled();
    expect(result.current.detail).toEqual(DAY);
  });

  it('passes a named date through untouched', async () => {
    const { result } = renderHook(() => useDay('2026-08-14'));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(getDay).toHaveBeenCalledWith('2026-08-14');
    expect(result.current.error).toBeNull();
  });

  it('re-fetches when the date changes', async () => {
    const { result, rerender } = renderHook(({ date }) => useDay(date), {
      initialProps: { date: '2026-08-14' as string | null },
    });
    await waitFor(() => expect(result.current.loading).toBe(false));

    rerender({ date: '2026-08-30' });
    await waitFor(() => expect(getDay).toHaveBeenCalledTimes(2));

    expect(getDay).toHaveBeenLastCalledWith('2026-08-30');
  });

  it('reports a failure and does not keep showing the day that failed', async () => {
    getDay = mock(() => Promise.reject(new Error('404: no rule covers 1999-01-01')));

    const { result } = renderHook(() => useDay('1999-01-01'));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toContain('1999-01-01');
    expect(result.current.detail).toBeNull();
  });

  it('reads a day without claiming a person opened it', async () => {
    // The default read is the one an agent, an import or a cron job makes.
    // Only a screen says "opened", and only that fills `day.opened_at`.
    const { result } = renderHook(() => useDay('2026-08-30'));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(getDay).toHaveBeenCalledWith('2026-08-30');
    expect(openDay).not.toHaveBeenCalled();
  });

  it('says a person is looking when asked to', async () => {
    const { result } = renderHook(() => useDay('2026-08-30', true));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(openDay).toHaveBeenCalledWith('2026-08-30');
    expect(getDay).not.toHaveBeenCalled();
  });

  it('opens today the same way when no date is given', async () => {
    const { result } = renderHook(() => useDay(null, true));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(openToday).toHaveBeenCalled();
    expect(getToday).not.toHaveBeenCalled();
  });

  it('reloads on demand', async () => {
    const { result } = renderHook(() => useDay('2026-08-30'));
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => result.current.reload());
    await waitFor(() => expect(getDay).toHaveBeenCalledTimes(2));
  });
});
