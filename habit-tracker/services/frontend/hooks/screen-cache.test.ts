// [review:need-review] #311
// summary: #311 round 3 — a cached «today» of the day screen is drawn at once but not written into until the server confirms it (same day unlocks, D+1 moves the screen, a failed re-read keeps it locked); the server's day older than DAY_TRUST_MS is not drawn, a failed re-read is reported by every screen hook while its data stays, and a Today snapshot of a day the server no longer names is not writable on a re-visit
// summary: tests across the screen hooks on the shared read cache — every hook of the registry draws its second visit from the cache with no spinner while the server does not answer, Today and its buttons read the directory once and both follow the re-read when the tab comes back, and the end of a session (logout, 401) leaves nothing to draw

import { afterEach, beforeEach, describe, expect, it, jest, mock } from 'bun:test';
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
  RoleActDraft,
  RoleDay,
  Week,
} from '@/lib/api';
import { getQueryData, setQueryData } from '@/lib/query-cache';

const realApi = await import('@/lib/api');

/** What every read of the suite does: answer, hang (the server is silent), or fail. */
let server: 'answers' | 'hangs' | 'fails' = 'answers';
/** Reads that hang whatever `server` says, by name. */
let hanging = new Set<string>();
let listMarks: ReturnType<typeof mock>;
let createEntry: ReturnType<typeof mock>;

function answer<T>(value: T, name = ''): Promise<T> {
  if (server === 'hangs' || hanging.has(name)) return new Promise<T>(() => {});
  if (server === 'fails') return Promise.reject(new Error('offline'));
  return Promise.resolve(value);
}

const DAY = '2026-11-01';
const NEXT_DAY = '2026-11-02';

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
const NEXT_DAY_DETAIL = { day: { date: '2026-11-02' } } as unknown as DayDetail;
let todayDetail = DAY_DETAIL;
let setMark: ReturnType<typeof mock>;
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
let dayModeNow = DAY_MODE;

// The real module stays under the entries this suite replaces: the export names
// of a module are fixed by whichever suite links it first. `dashboardAPI` is left
// real on purpose — the dashboard page suite reads it through a stubbed fetch, and
// a module mock outlives the file that set it; the hook takes its source instead.
mock.module('@/lib/api', () => ({
  ...realApi,
  agentAPI: { ...realApi.agentAPI, dayMode: () => answer(dayModeNow, 'dayMode') },
  categoriesAPI: {
    ...realApi.categoriesAPI,
    getAll: () => answer(CATEGORIES),
    getStreaks: () => answer([]),
  },
  entriesAPI: {
    ...realApi.entriesAPI,
    getAll: () => answer(ENTRIES, 'entries'),
    create: () => createEntry(),
  },
  quickMarksAPI: { ...realApi.quickMarksAPI, list: () => listMarks() },
  challengesAPI: { ...realApi.challengesAPI, list: () => answer(CHALLENGES) },
  dayAPI: {
    ...realApi.dayAPI,
    open: () => answer(DAY_DETAIL),
    openToday: () => answer(todayDetail),
    setMark: (...args: unknown[]) => setMark(...args),
    violations: () => answer([]),
  },
  weeksAPI: { ...realApi.weeksAPI, getCurrent: () => answer(WEEK) },
  daysAPI: { ...realApi.daysAPI, range: () => answer(DAYS) },
  // The writes always go through: the suite is about the re-read behind them.
  goalsAPI: { ...realApi.goalsAPI, get: () => answer(GOALS), patchMilestone: () => Promise.resolve({}) },
  journalAPI: { ...realApi.journalAPI, getAll: () => answer({ items: JOURNAL, total: 0 }) },
  rolesAPI: {
    ...realApi.rolesAPI,
    day: () => answer(ROLE_DAY),
    listRoles: () => answer(ROLES),
    addAct: () => Promise.resolve({}),
  },
}));

const { useServerDay } = await import('./useServerDay');
const { useCategories } = await import('./useCategories');
const { useQuickMarks } = await import('./useQuickMarks');
const { useDashboardSummary } = await import('./useDashboardSummary');
const { useDay } = await import('./useDay');
const { useDayMarks } = await import('./useDayMarks');
const NO_DAY_MARKS: never[] = [];
const NO_KINDS = new Map<string, string>();
const { useWeek } = await import('./useWeek');
const { useDays } = await import('./useDays');
const { useGoals } = await import('./useGoals');
const { useJournal } = await import('./useJournal');
const { useRoles } = await import('./useRoles');
const { useChallenges } = await import('./useChallenges');
const { useToday, DAY_RECHECK_MS, DAY_UNCONFIRMED } = await import('./useToday');
const { DAY_TRUST_MS } = await import('./useServerDay');

beforeEach(() => {
  server = 'answers';
  hanging = new Set();
  dayModeNow = DAY_MODE;
  listMarks = mock(() => answer([MARK]));
  createEntry = mock(() => new Promise(() => {}));
  todayDetail = DAY_DETAIL;
  setMark = mock(() => Promise.resolve({ item_id: 'a', state: 'done', note: null }));
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

      server = 'hangs';
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
    server = 'hangs';
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

/** Run `body` with the clock moved `ms` ahead. */
async function later<T>(ms: number, body: () => T | Promise<T>): Promise<T> {
  const realNow = Date.now;
  Date.now = () => realNow() + ms;
  try {
    return await body();
  } finally {
    Date.now = realNow;
  }
}

describe('a cached «today» goes stale with the clock', () => {
  /** The day screen's read and its marks, as the screen wires them. */
  function useTodayScreen() {
    const day = useDay(null, true);
    const marks = useDayMarks(day.writeDate, NO_DAY_MARKS, NO_KINDS);
    return { day, marks };
  }

  async function visitedEarlier() {
    const first = renderHook(useTodayScreen);
    await waitFor(() => expect(first.result.current.day.writeDate).toBe(DAY));
    first.unmount();
  }

  it('(a) a re-visit after the window draws the cached today at once, and a mark waits', async () => {
    await visitedEarlier();
    server = 'hangs';

    await later(DAY_TRUST_MS + 1_000, async () => {
      const frames: (DayDetail | null)[] = [];
      const { result } = renderHook(() => {
        const screen = useTodayScreen();
        frames.push(screen.day.detail);
        return screen;
      });
      expect(frames[0]).toEqual(DAY_DETAIL);
      expect(result.current.day.writeDate).toBe('');

      await act(async () => {
        result.current.marks.setState('a', 'done');
      });
      expect(setMark).not.toHaveBeenCalled();
    });
  });

  it('(b) the server confirming the same day unlocks the marks', async () => {
    await visitedEarlier();

    await later(DAY_TRUST_MS + 1_000, async () => {
      const { result } = renderHook(useTodayScreen);
      await waitFor(() => expect(result.current.day.writeDate).toBe(DAY));
      await act(async () => {
        result.current.marks.setState('a', 'done');
      });
      expect(setMark).toHaveBeenCalledTimes(1);
      expect(setMark.mock.calls[0][0]).toBe(DAY);
    });
  });

  it('(c) the server naming the next day moves the screen there, and nothing goes to yesterday', async () => {
    await visitedEarlier();
    todayDetail = NEXT_DAY_DETAIL;

    await later(DAY_TRUST_MS + 1_000, async () => {
      const { result } = renderHook(useTodayScreen);
      await act(async () => {
        result.current.marks.setState('a', 'done');
      });
      await waitFor(() => expect(result.current.day.writeDate).toBe(NEXT_DAY));
      expect(result.current.day.detail).toEqual(NEXT_DAY_DETAIL);
      expect(setMark.mock.calls.map((call) => call[0])).not.toContain(DAY);
    });
  });

  it('(d) a failed re-read keeps the day on screen, says so, and keeps the marks locked', async () => {
    await visitedEarlier();
    server = 'fails';

    await later(DAY_TRUST_MS + 1_000, async () => {
      const { result } = renderHook(useTodayScreen);
      await waitFor(() => expect(result.current.day.error).toBe('offline'));
      expect(result.current.day.detail).toEqual(DAY_DETAIL);
      expect(result.current.day.writeDate).toBe('');
      await act(async () => {
        result.current.marks.setState('a', 'done');
      });
      expect(setMark).not.toHaveBeenCalled();
    });
  });

  it('a named date is written into at once, cached or not', async () => {
    const { result } = renderHook(() => useDay(DAY, true));
    await waitFor(() => expect(result.current.writeDate).toBe(DAY));
  });

  it('useServerDay neither shows nor settles a cached day older than the window', async () => {
    const first = renderHook(() => useServerDay());
    await waitFor(() => expect(first.result.current.settled).toBe(true));
    first.unmount();
    server = 'fails';

    await later(DAY_TRUST_MS + 1_000, async () => {
      const { result } = renderHook(() => useServerDay());
      expect(result.current).toEqual({ date: '', settled: false });
      await waitFor(() => expect(result.current.settled).toBe(true));
      expect(result.current.date).toBe('');
    });
  });
});

describe('a failed re-read is said while the earlier data stays', () => {
  const REREADS: { name: string; useScreen: () => { error: string | null; shown: boolean; reread: () => unknown } }[] = [
    {
      name: 'useGoals',
      useScreen: () => {
        const goals = useGoals();
        return { error: goals.error, shown: goals.payload !== null, reread: () => goals.markMilestone('M1', 'done') };
      },
    },
    {
      name: 'useRoles',
      useScreen: () => {
        const roles = useRoles();
        return { error: roles.error, shown: roles.day !== null, reread: () => roles.addAct({} as RoleActDraft) };
      },
    },
    {
      name: 'useChallenges',
      useScreen: () => {
        const challenges = useChallenges();
        return { error: challenges.error, shown: !challenges.loading, reread: challenges.reload };
      },
    },
    {
      name: 'useDay',
      useScreen: () => {
        const day = useDay(DAY, true);
        return { error: day.error, shown: day.detail !== null, reread: day.reload };
      },
    },
    {
      name: 'useWeek',
      useScreen: () => {
        const week = useWeek(null);
        return { error: week.error, shown: week.week !== null, reread: week.reload };
      },
    },
    {
      name: 'useDays',
      useScreen: () => {
        const days = useDays('2026-10-26', DAY);
        return { error: days.error, shown: !days.loading, reread: days.reload };
      },
    },
  ];

  for (const { name, useScreen } of REREADS) {
    it(`${name} reports the failed re-read and keeps its data`, async () => {
      const { result } = renderHook(useScreen);
      await waitFor(() => expect(result.current.shown).toBe(true));

      server = 'fails';
      await act(async () => {
        await result.current.reread();
      });

      await waitFor(() => expect(result.current.error).toBe('offline'));
      expect(result.current.shown).toBe(true);
    });
  }
});

describe('Today: a cached day the server no longer names is not written into', () => {
  async function revisitAndWrite() {
    server = 'hangs';
    const { result } = renderHook(() => useToday());
    expect(result.current.date).toBe(DAY);
    await act(async () => {
      void result.current.addNumber(5, 9, 1);
    });
    return result;
  }

  it('control: a day confirmed a moment ago is written into on a re-visit', async () => {
    const first = renderHook(() => useToday());
    await waitFor(() => expect(first.result.current.loading).toBe(false));
    first.unmount();

    await revisitAndWrite();
    expect(createEntry).toHaveBeenCalledTimes(1);
  });

  it('a snapshot read that heard the next day withdraws the old one, even before the screen moved', async () => {
    const first = renderHook(() => useToday());
    await waitFor(() => expect(first.result.current.loading).toBe(false));

    // The day read answers D+1 while the records of the snapshot hang.
    dayModeNow = { ...DAY_MODE, date: NEXT_DAY };
    hanging.add('entries');
    act(() => {
      void first.result.current.reload();
    });
    await waitFor(() => expect(getQueryData<{ date: string }>('today:confirmedDay')?.date).toBe(NEXT_DAY));
    // A write on the screen still on D keeps the snapshot of D being written.
    await act(async () => {
      void first.result.current.addNumber(5, 9, 1);
    });
    expect(first.result.current.date).toBe(DAY);
    first.unmount();
    createEntry.mockClear();

    const result = await revisitAndWrite();
    expect(createEntry).not.toHaveBeenCalled();
    expect(result.current.error).toBe(DAY_UNCONFIRMED);
  });

  it('a minute recheck that heard the next day withdraws the old one', async () => {
    // The recheck is an interval set at mount: the fake clock has to be there first,
    // and the waits below flush promises instead of polling on timers.
    jest.useFakeTimers();
    try {
      const first = renderHook(() => useToday());
      for (let n = 0; n < 10 && first.result.current.loading; n += 1) {
        await act(async () => {
          await Promise.resolve();
        });
      }
      expect(first.result.current.loading).toBe(false);

      dayModeNow = { ...DAY_MODE, date: NEXT_DAY };
      hanging.add('entries');
      await act(async () => {
        jest.advanceTimersByTime(DAY_RECHECK_MS);
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(getQueryData<{ date: string }>('today:confirmedDay')?.date).toBe(NEXT_DAY);
      expect(first.result.current.date).toBe(DAY);
      first.unmount();
    } finally {
      jest.useRealTimers();
    }

    await revisitAndWrite();
    expect(createEntry).not.toHaveBeenCalled();
  });
});
