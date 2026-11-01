// [review:need-review] #311
// summary: tests across the screen hooks on the shared read cache — every hook of the registry draws its second visit from the cache with no spinner while the server does not answer, Today and its buttons read the directory once and both follow the re-read when the tab comes back, and the end of a session (logout, 401) leaves nothing to draw

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import type {
  Category,
  Challenge,
  DashboardSummary,
  DayDetail,
  DayListItem,
  DayMode,
  Entry,
  GoalsPayload,
  JournalEntry,
  QuickMark,
  Role,
  RoleDay,
  Week,
} from '@/lib/api';
import { getQueryData, setQueryData } from '@/lib/query-cache';

const realApi = await import('@/lib/api');

/** While false, every read of the suite hangs: the server does not answer. */
let answering = true;
let listMarks: ReturnType<typeof mock>;

function answer<T>(value: T): Promise<T> {
  return answering ? Promise.resolve(value) : new Promise<T>(() => {});
}

const DAY = '2026-11-01';

const MARK = {
  id: 3,
  label: 'Вода',
  category_id: 5,
  field_id: 9,
  kind: 'increment',
  step: 250,
  unit_label: 'мл',
  icon: null,
  color: null,
  hotkey: null,
  order: 0,
  show_in_agent: true,
  is_active: true,
  entry_date: DAY,
  today_total: 500,
  done: true,
  planned: false,
  plan_item_id: null,
} satisfies QuickMark;

// Only the shape each hook reads is filled in: the hooks pass these through.
const CATEGORIES: Category[] = [];
const ENTRIES: Entry[] = [];
const DAY_DETAIL = { day: { date: DAY } } as unknown as DayDetail;
const WEEK = { iso_code: '2026-W44', starts_on: '2026-10-26', ends_on: DAY } as unknown as Week;
const DAYS: DayListItem[] = [];
const GOALS = { levels: [] } as unknown as GoalsPayload;
const JOURNAL: JournalEntry[] = [];
const ROLE_DAY = { date: DAY } as unknown as RoleDay;
const ROLES: Role[] = [];
const CHALLENGES: Challenge[] = [];
const SUMMARY = { period: 'week' } as unknown as DashboardSummary;
const readSummary = () => answer(SUMMARY);
const DAY_MODE = { date: DAY, kind: 'work', nocode: false, source: 'schedule' } as unknown as DayMode;

// The real module stays under the entries this suite replaces: the export names
// of a module are fixed by whichever suite links it first. `dashboardAPI` is left
// real on purpose — the dashboard page suite reads it through a stubbed fetch, and
// a module mock outlives the file that set it; the hook takes its source instead.
mock.module('@/lib/api', () => ({
  ...realApi,
  agentAPI: { ...realApi.agentAPI, dayMode: () => answer(DAY_MODE) },
  categoriesAPI: {
    ...realApi.categoriesAPI,
    getAll: () => answer(CATEGORIES),
    getStreaks: () => answer([]),
  },
  entriesAPI: { ...realApi.entriesAPI, getAll: () => answer(ENTRIES) },
  quickMarksAPI: { ...realApi.quickMarksAPI, list: () => listMarks() },
  challengesAPI: { ...realApi.challengesAPI, list: () => answer(CHALLENGES) },
  dayAPI: { ...realApi.dayAPI, open: () => answer(DAY_DETAIL), violations: () => answer([]) },
  weeksAPI: { ...realApi.weeksAPI, getCurrent: () => answer(WEEK) },
  daysAPI: { ...realApi.daysAPI, range: () => answer(DAYS) },
  goalsAPI: { ...realApi.goalsAPI, get: () => answer(GOALS) },
  journalAPI: { ...realApi.journalAPI, getAll: () => answer({ items: JOURNAL, total: 0 }) },
  rolesAPI: { ...realApi.rolesAPI, day: () => answer(ROLE_DAY), listRoles: () => answer(ROLES) },
}));

const { useServerDay } = await import('./useServerDay');
const { useCategories } = await import('./useCategories');
const { useQuickMarks } = await import('./useQuickMarks');
const { useDashboardSummary } = await import('./useDashboardSummary');
const { useDay } = await import('./useDay');
const { useWeek } = await import('./useWeek');
const { useDays } = await import('./useDays');
const { useGoals } = await import('./useGoals');
const { useJournal } = await import('./useJournal');
const { useRoles } = await import('./useRoles');
const { useChallenges } = await import('./useChallenges');
const { useToday } = await import('./useToday');

beforeEach(() => {
  answering = true;
  listMarks = mock(() => answer([MARK]));
});

afterEach(() => {
  cleanup();
});

/** Every screen hook moved onto the cache, reduced to "is it showing a spinner". */
const SCREENS: { name: string; useScreen: () => boolean }[] = [
  { name: 'useServerDay', useScreen: () => !useServerDay().settled },
  { name: 'useCategories', useScreen: () => useCategories().loading },
  { name: 'useQuickMarks', useScreen: () => useQuickMarks().loading },
  {
    name: 'useDashboardSummary',
    useScreen: () => useDashboardSummary(readSummary).state.status === 'loading',
  },
  { name: 'useDay', useScreen: () => useDay(DAY, true).loading },
  { name: 'useWeek', useScreen: () => useWeek(null).loading },
  { name: 'useDays', useScreen: () => useDays('2026-10-26', DAY).loading },
  { name: 'useGoals', useScreen: () => useGoals().loading },
  { name: 'useJournal', useScreen: () => useJournal().loading },
  { name: 'useRoles', useScreen: () => useRoles().loading },
  { name: 'useChallenges', useScreen: () => useChallenges().loading },
  { name: 'useToday', useScreen: () => useToday().loading },
];

describe('screen hooks: a second visit with the cache filled', () => {
  for (const { name, useScreen } of SCREENS) {
    it(`${name} draws its first frame without a spinner while the server does not answer`, async () => {
      const first = renderHook(useScreen);
      await waitFor(() => expect(first.result.current).toBe(false));
      first.unmount();

      answering = false;
      const frames: boolean[] = [];
      renderHook(() => {
        const loading = useScreen();
        frames.push(loading);
        return loading;
      });

      expect(frames[0]).toBe(false);
    });
  }
});

describe('Today: one copy of the quick-mark directory', () => {
  function useTodayWithButtons() {
    const today = useToday();
    const buttons = useQuickMarks({ onDayChanged: today.reloadAfterMark });
    return { today, buttons };
  }

  it('reads the directory once for the snapshot and the buttons together', async () => {
    const { result } = renderHook(useTodayWithButtons);
    await waitFor(() => expect(result.current.today.loading).toBe(false));
    await waitFor(() => expect(result.current.buttons.loading).toBe(false));

    expect(listMarks).toHaveBeenCalledTimes(1);
    expect(result.current.buttons.marks).toEqual(result.current.today.quickMarks);
  });

  it('shows the buttons the re-read brought when the tab comes back', async () => {
    const { result } = renderHook(useTodayWithButtons);
    await waitFor(() => expect(result.current.buttons.marks[0]?.today_total).toBe(500));

    // Another device tapped meanwhile.
    listMarks = mock(() => answer([{ ...MARK, today_total: 750 }]));
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'));
    });

    await waitFor(() => expect(result.current.buttons.marks[0]?.today_total).toBe(750));
    expect(result.current.today.quickMarks[0]?.today_total).toBe(750);
    expect(listMarks).toHaveBeenCalledTimes(1);
  });
});

describe('the end of a session', () => {
  const realFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = realFetch;
  });

  function respond(status: number, body: unknown) {
    globalThis.fetch = mock(() =>
      Promise.resolve(new Response(JSON.stringify(body), { status }))
    ) as unknown as typeof fetch;
  }

  it('a logout empties the cache, and the next screen shows nothing of the previous one', async () => {
    const first = renderHook(() => useGoals());
    await waitFor(() => expect(first.result.current.loading).toBe(false));
    first.unmount();
    respond(200, { authenticated: false, expires_in_s: null });

    await realApi.authAPI.logout();

    expect(getQueryData('goals')).toBeUndefined();
    answering = false;
    const { result } = renderHook(() => useGoals());
    expect(result.current.loading).toBe(true);
    expect(result.current.payload).toBeNull();
  });

  it('a 401 on any request empties the cache', async () => {
    setQueryData('journal', JOURNAL);
    // The login screen itself: a 401 there is a message, not a redirect this test would follow.
    window.history.replaceState(null, '', '/login');
    respond(401, { detail: 'Not authenticated' });

    await expect(realApi.authAPI.status()).rejects.toThrow('Not authenticated');

    expect(getQueryData('journal')).toBeUndefined();
    window.history.replaceState(null, '', '/');
  });
});
