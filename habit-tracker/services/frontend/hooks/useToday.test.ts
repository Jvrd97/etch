// [review:need-review] PHASE-01/61-today-total-owned-by-hook, PHASE-03/121, PHASE-03/124, PHASE-03/123, PHASE-01/177, PHASE-01/206, PHASE-03/237, PHASE-03/247, PHASE-03/253, PHASE-03/257
// summary: tests for useToday — the targeted re-read after a quick mark (records, ticks and the one streak that can have moved, nothing else, and never an older answer over a newer one), silent visibility refetch, the two rounds of the cold path (the buttons land after the first, the streaks report themselves from the second and a tap goes through while they are still in flight), the optimistic number increment with per-tap rollback, the quick-mark tap that costs one request and repaints from its own answer, the retry that sends the second attempt under the key of the first, and the undo that puts the day back
// summary: #257 — the badge's read joins the day read in flight, but `{ fresh: true }` (its retry after a lost read) starts a new request
// summary: #247/#253 — the screen and its day-mode badge share one read of the day (same day, one request, the badge's answer moves the screen); records ask in parallel with the day; a day not confirmed by three minute reads in a row refuses writes and says so once; a failed tick rolls back only on its own day; no snapshot after unmount; the retry of a failed first load stays quiet
// summary: the server day in useToday: the header, the records read, the re-read after a mark, the checklist tick and the increment use the day of GET /day-mode while the browser is a day behind; a changed day is followed on return to the tab and by the minute timer (fake timers); an older snapshot, a tick or a re-read of a finished day never lands over the new day; a day that cannot be read leaves no screen and no request for records

import { afterEach, beforeEach, describe, expect, it, jest, mock, spyOn } from 'bun:test';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import type {
  Category,
  Entry,
  Field,
  QuickMark,
  QuickMarkEvent,
  QuickMarkUndo,
} from '@/lib/api';
import { isFieldChecked, numberFieldSum } from '@/lib/today-entries';

const TIMESTAMP = '2026-07-24T00:00:00Z';
const TODAY = '2026-07-24';
// The day the browser believes it is: a zone behind the server (Pacific/Pago_Pago
// at 23:00 UTC), or 00:30 before the boundary hour. Never the server's day, so
// any read of the browser clock shows up as a different date in a request.
const BROWSER_DAY = '2026-07-23';
const DAY_BEFORE_BROWSER = '2026-07-22';
// The explicit page size of the records window: a full page may have lost its tail.
const WINDOW_LIMIT = 1000;

const GLASSES_FIELD: Field = {
  id: 7,
  category_id: 1,
  name: 'Glasses',
  field_type: 'number',
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
  fields: [GLASSES_FIELD],
};

/**
 * A category with an avoid streak — the only thing that makes the second round
 * of the cold path non-empty, since streaks are read one per avoid category.
 */
const SMOKING: Category = {
  id: 2,
  name: 'Smoking',
  display_mode: 'form',
  streak_mode: 'avoid',
  is_active: true,
  created_at: TIMESTAMP,
  updated_at: TIMESTAMP,
  fields: [],
};

const ENTRY: Entry = {
  id: 10,
  category_id: 1,
  entry_date: TODAY,
  created_at: TIMESTAMP,
  updated_at: TIMESTAMP,
  values: [],
};

/** A saved entry as the API would echo it back. */
function savedEntry(id: number, amount: number): Entry {
  return {
    id,
    category_id: CATEGORY.id,
    entry_date: TODAY,
    created_at: TIMESTAMP,
    updated_at: TIMESTAMP,
    values: [
      { id, entry_id: id, field_id: GLASSES_FIELD.id, value: String(amount) },
    ],
  };
}

/** Today's total for the number field, as the screens compute it. */
function totalOf(entries: Entry[]): number {
  return numberFieldSum(entries, CATEGORY.id, GLASSES_FIELD.id);
}

/** What `GET /day-mode` answers: the day the server is running, named by `date`. */
function dayModeOf(date: string) {
  return { date, kind: 'work', nocode: false, source: 'schedule' };
}

/** Resolves only when the test releases it, so a refetch can be observed mid-flight. */
function deferred<T>(): {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason: Error) => void;
} {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

let getAllCategories: ReturnType<typeof mock>;
let getAllEntries: ReturnType<typeof mock>;
let readDayMode: ReturnType<typeof mock>;
let writeDayMode: ReturnType<typeof mock>;
let createEntry: ReturnType<typeof mock>;
let deleteEntry: ReturnType<typeof mock>;
let upsertChecklist: ReturnType<typeof mock>;
let listQuickMarks: ReturnType<typeof mock>;
let getStreakApi: ReturnType<typeof mock>;
let getStreaksApi: ReturnType<typeof mock>;
let tapQuickMarkApi: ReturnType<typeof mock>;
let undoQuickMarkApi: ReturnType<typeof mock>;

/** The «+250 мл» button, as the directory returns it. */
const WATER_MARK: QuickMark = {
  id: 3,
  label: '+250 мл',
  category_id: CATEGORY.id,
  field_id: GLASSES_FIELD.id,
  kind: 'increment',
  step: 250,
  unit_label: 'мл',
  icon: null,
  color: null,
  hotkey: null,
  order: 0,
  show_in_agent: true,
  is_active: true,
  entry_date: TODAY,
  today_total: null,
  done: false,
  planned: false,
  plan_item_id: null,
};

/** What the one POST of a tap answers with. */
function tapAnswer(total: number): QuickMarkEvent {
  return {
    event_id: 1,
    quick_mark_id: WATER_MARK.id,
    entry_id: 42,
    entry_date: TODAY,
    occurred_at: TIMESTAMP,
    today_total: total,
    done: true,
  };
}

/** What the one POST of an undo answers with. */
function undoAnswer(total: number): QuickMarkUndo {
  return {
    event_id: 1,
    quick_mark_id: WATER_MARK.id,
    entry_date: TODAY,
    undone_at: TIMESTAMP,
    today_total: total,
    done: total > 0,
  };
}

// The whole module is replaced process-wide, so the members other suites reach
// for have to stay present even though this one never calls them.
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
    setDayMode: (date: string, draft: unknown) => writeDayMode(date, draft),
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
    list: () => listQuickMarks(),
    tap: (id: number, tap: unknown, key?: string) => tapQuickMarkApi(id, tap, key),
    undo: (eventId: number) => undoQuickMarkApi(eventId),
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
    getStreak: (id: number) => getStreakApi(id),
    getStreaks: (mode: 'avoid' | 'build') => getStreaksApi(mode),
    create: () => Promise.resolve(null),
    update: () => Promise.resolve(null),
    delete: () => Promise.resolve(undefined),
  },
  entriesAPI: {
    getAll: (params?: unknown) => getAllEntries(params),
    create: (data: unknown) => createEntry(data),
    update: () => Promise.resolve(null),
    delete: (id: number) => deleteEntry(id),
    upsertChecklist: (data: unknown) => upsertChecklist(data),
  },
  journalAPI: {
    getAll: () => Promise.resolve({ items: [], total: 0 }),
    getById: () => Promise.resolve(null),
    create: () => Promise.resolve(null),
  },
  tableAPI: { get: () => Promise.resolve({ days: [] }) },
}));

// Copied before mocking: bun rewrites a mocked module's namespace in place, and the rest of
// `@/lib/date` must stay for every file that links after this one.
const realDate = { ...(await import('@/lib/date')) };
mock.module('@/lib/date', () => ({ ...realDate, todayISO: () => BROWSER_DAY }));

const { useToday, STREAKS_FAILED, DAY_RECHECK_MS, DAY_POLL_FAILURES_LIMIT, DAY_UNCONFIRMED } =
  await import('./useToday');
const { useDayMode } = await import('./useDayMode');
const { useTodayDayModeSync } = await import('./useTodayDayModeSync');
const { entriesAPI } = await import('@/lib/api');

beforeEach(() => {
  getAllCategories = mock(() => Promise.resolve([CATEGORY]));
  getAllEntries = mock(() => Promise.resolve([ENTRY]));
  readDayMode = mock(() => Promise.resolve(dayModeOf(TODAY)));
  writeDayMode = mock((date: string) => Promise.resolve(dayModeOf(date)));
  createEntry = mock(() => Promise.resolve(savedEntry(11, 1)));
  deleteEntry = mock(() => Promise.resolve(undefined));
  upsertChecklist = mock(() => Promise.resolve(ENTRY));
  listQuickMarks = mock(() => Promise.resolve([WATER_MARK]));
  getStreakApi = mock(() => Promise.resolve(null));
  getStreaksApi = mock(() => Promise.resolve([]));
  tapQuickMarkApi = mock(() => Promise.resolve(tapAnswer(250)));
  undoQuickMarkApi = mock(() => Promise.resolve(undoAnswer(0)));
});

afterEach(() => {
  cleanup();
});

describe('the two rounds of the cold path', () => {
  it('hands over the screen after the first round, with the streaks still in flight', async () => {
    const pendingStreak = deferred<[]>();
    getAllCategories = mock(() => Promise.resolve([CATEGORY, SMOKING]));
    getStreaksApi = mock(() => pendingStreak.promise);

    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    // Кнопки и записи есть, стрики ещё едут — это и есть состояние, ради
    // которого круги разведены.
    expect(result.current.streaksLoading).toBe(true);
    expect(result.current.entries).toEqual([ENTRY]);
    expect(result.current.quickMarks).toEqual([WATER_MARK]);
    expect(getStreaksApi).toHaveBeenCalledWith('avoid');

    await act(async () => {
      pendingStreak.resolve([]);
      await Promise.resolve();
    });
    await waitFor(() => expect(result.current.streaksLoading).toBe(false));
  });

  it('records a tap while the streaks are still loading', async () => {
    const pendingStreak = deferred<[]>();
    getAllCategories = mock(() => Promise.resolve([CATEGORY, SMOKING]));
    getStreaksApi = mock(() => pendingStreak.promise);

    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.streaksLoading).toBe(true);

    await act(async () => {
      await result.current.tapQuickMark(WATER_MARK.id);
    });

    expect(tapQuickMarkApi).toHaveBeenCalledTimes(1);
    expect(result.current.quickMarks[0].today_total).toBe(250);

    await act(async () => {
      pendingStreak.resolve([]);
      await Promise.resolve();
    });
  });

  it('keeps a failed streak inside its own section rather than on the screen', async () => {
    getAllCategories = mock(() => Promise.resolve([CATEGORY, SMOKING]));
    getStreaksApi = mock(() => Promise.reject(new Error('streaks are down')));

    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.streaksLoading).toBe(false));

    expect(result.current.streaksError).toBe(STREAKS_FAILED);
    // The buttons are the point: a streak that did not load must not take them
    // off the screen, and must not raise the screen-wide error either.
    expect(result.current.error).toBeNull();
    expect(result.current.quickMarks).toEqual([WATER_MARK]);
  });

  it('says nothing about streaks when every one of them arrived', async () => {
    getAllCategories = mock(() => Promise.resolve([CATEGORY, SMOKING]));
    getStreaksApi = mock(() => Promise.resolve([{
      category_id: SMOKING.id,
      streak_mode: 'avoid' as const,
      current_streak: 3,
      best_streak: 7,
      last_relapse_date: null,
    }]));

    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.streaksLoading).toBe(false));

    expect(result.current.streaksError).toBeNull();
    expect(getStreaksApi).toHaveBeenCalledTimes(1);
  });
});

describe('useToday', () => {
  it('shows the spinner on the initial load', async () => {
    const { result } = renderHook(() => useToday());

    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.entries).toEqual([ENTRY]);
  });

  it('refetches silently when the tab becomes visible again', async () => {
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    const pendingCategories = deferred<Category[]>();
    const pendingEntries = deferred<Entry[]>();
    getAllCategories = mock(() => pendingCategories.promise);
    getAllEntries = mock(() => pendingEntries.promise);

    act(() => {
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await waitFor(() => expect(getAllEntries).toHaveBeenCalled());

    // Mid-flight: no spinner, and the previously loaded data is still rendered.
    expect(result.current.loading).toBe(false);
    expect(result.current.entries).toEqual([ENTRY]);

    await act(async () => {
      pendingCategories.resolve([CATEGORY]);
      pendingEntries.resolve([ENTRY]);
      await Promise.resolve();
    });
    expect(result.current.loading).toBe(false);
  });

  it('clears a stale error once a later fetch succeeds', async () => {
    getAllCategories = mock(() => Promise.reject(new Error('network down')));
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.error).toBe('network down'));

    getAllCategories = mock(() => Promise.resolve([CATEGORY]));
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'));
    });

    await waitFor(() => expect(result.current.error).toBeNull());
  });
});

describe('useToday takes the day from the server', () => {
  const NEXT_DAY = '2026-07-25';
  const CHECKLIST: Category = {
    ...CATEGORY,
    id: 3,
    display_mode: 'checklist',
    fields: [{ ...GLASSES_FIELD, id: 8, category_id: 3, field_type: 'boolean' }],
  };

  it('names the server day in the header and reads the records of that day, not the browser\'s', async () => {
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(readDayMode).toHaveBeenCalledWith();
    expect(result.current.date).toBe(TODAY);
    // A window around the browser's day (a hint, one day behind here) that holds the
    // server's day: the records of the day are cut from it, no second read.
    expect(getAllEntries).toHaveBeenCalledTimes(1);
    expect(getAllEntries).toHaveBeenCalledWith({ startDate: DAY_BEFORE_BROWSER, endDate: TODAY, limit: WINDOW_LIMIT });
  });

  it('asks for the records while the day is still unanswered, not after it', async () => {
    const slowDay = deferred<ReturnType<typeof dayModeOf>>();
    readDayMode = mock(() => slowDay.promise);
    const { result } = renderHook(() => useToday());

    await waitFor(() => expect(getAllEntries).toHaveBeenCalled());
    expect(result.current.loading).toBe(true);

    await act(async () => {
      slowDay.resolve(dayModeOf(TODAY));
      await Promise.resolve();
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.entries).toEqual([ENTRY]);
  });

  it('keeps only the records of the server day out of the window', async () => {
    const yesterdays: Entry = { ...ENTRY, id: 9, entry_date: BROWSER_DAY };
    getAllEntries = mock(() => Promise.resolve([ENTRY, yesterdays]));
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.entries).toEqual([ENTRY]);
  });

  it('reads the day exactly when the server day is outside the window', async () => {
    readDayMode = mock(() => Promise.resolve(dayModeOf('2026-08-30')));
    getAllEntries = mock((params: { startDate: string }) =>
      Promise.resolve(params.startDate === '2026-08-30' ? [{ ...ENTRY, entry_date: '2026-08-30' }] : [ENTRY])
    );
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(getAllEntries).toHaveBeenLastCalledWith({ startDate: '2026-08-30', endDate: '2026-08-30' });
    expect(result.current.entries).toEqual([{ ...ENTRY, entry_date: '2026-08-30' }]);
  });

  it('writes a checklist tick and a number increment to the server day', async () => {
    getAllCategories = mock(() => Promise.resolve([CATEGORY, CHECKLIST]));
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.toggleField(CHECKLIST.id, 8);
      await result.current.addNumber(CATEGORY.id, GLASSES_FIELD.id, 250);
    });

    expect(upsertChecklist).toHaveBeenCalledWith(
      expect.objectContaining({ category_id: CHECKLIST.id, entry_date: TODAY })
    );
    expect(createEntry).toHaveBeenCalledWith(expect.objectContaining({ entry_date: TODAY }));
  });

  it('reads the records of the server day again after a mark', async () => {
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));
    getAllEntries.mockClear();

    await act(async () => {
      await result.current.reloadAfterMark(CATEGORY.id);
    });

    expect(getAllEntries).toHaveBeenCalledWith({ startDate: TODAY, endDate: TODAY });
  });

  it('follows the server across the day boundary when the tab comes back', async () => {
    createEntry = mock(() => Promise.resolve(savedEntry(11, 1)));
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.addNumber(CATEGORY.id, GLASSES_FIELD.id, 250);
    });
    expect(totalOf(result.current.entries)).toBe(250);

    readDayMode = mock(() => Promise.resolve(dayModeOf(NEXT_DAY)));
    getAllEntries = mock(() => Promise.resolve([]));
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await waitFor(() => expect(result.current.date).toBe(NEXT_DAY));

    expect(getAllEntries).toHaveBeenCalledWith({ startDate: BROWSER_DAY, endDate: NEXT_DAY, limit: WINDOW_LIMIT });
    // The increment belonged to yesterday and must not be counted into the new day.
    expect(result.current.entries).toEqual([]);

    await act(async () => {
      await result.current.addNumber(CATEGORY.id, GLASSES_FIELD.id, 100);
    });
    expect(createEntry).toHaveBeenLastCalledWith(
      expect.objectContaining({ entry_date: NEXT_DAY })
    );
  });

  it('shows the failure and no screen when the server day cannot be read', async () => {
    readDayMode = mock(() => Promise.reject(new Error('day unknown')));
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.error).toBe('day unknown'));

    // Falling back to the browser clock would write to a day the server does not run.
    expect(result.current.categories).toEqual([]);
    expect(result.current.date).toBe('');
    expect(result.current.entries).toEqual([]);
  });
});

describe('useToday keeps up with the server day', () => {
  const NEXT_DAY = '2026-07-25';

  afterEach(() => {
    jest.useRealTimers();
  });

  it('moves to the next day on its own timer, with no tab switch, so a tick never lands on yesterday', async () => {
    jest.useFakeTimers();
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.date).toBe(TODAY);

    readDayMode = mock(() => Promise.resolve(dayModeOf(NEXT_DAY)));
    getAllEntries = mock(() => Promise.resolve([]));
    await act(async () => {
      jest.advanceTimersByTime(DAY_RECHECK_MS);
    });
    await waitFor(() => expect(result.current.date).toBe(NEXT_DAY));

    expect(getAllEntries).toHaveBeenCalledWith({ startDate: BROWSER_DAY, endDate: NEXT_DAY, limit: WINDOW_LIMIT });
    await act(async () => {
      await result.current.addNumber(CATEGORY.id, GLASSES_FIELD.id, 100);
    });
    expect(createEntry).toHaveBeenLastCalledWith(
      expect.objectContaining({ entry_date: NEXT_DAY })
    );
  });

  it('costs one light read per tick while the day stays the same', async () => {
    jest.useFakeTimers();
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));
    getAllEntries.mockClear();
    getAllCategories.mockClear();
    readDayMode.mockClear();

    await act(async () => {
      jest.advanceTimersByTime(DAY_RECHECK_MS);
    });

    expect(readDayMode).toHaveBeenCalledTimes(1);
    expect(getAllEntries).not.toHaveBeenCalled();
    expect(getAllCategories).not.toHaveBeenCalled();
  });

  it('keeps the day it has when a tick cannot read the server', async () => {
    jest.useFakeTimers();
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    readDayMode = mock(() => Promise.reject(new Error('offline')));
    await act(async () => {
      jest.advanceTimersByTime(DAY_RECHECK_MS);
    });

    expect(result.current.date).toBe(TODAY);
    expect(result.current.error).toBeNull();
  });

  it('does not put a checklist tick saved for yesterday into the list of the new day', async () => {
    const checklist: Category = {
      ...CATEGORY,
      id: 3,
      display_mode: 'checklist',
      fields: [{ ...GLASSES_FIELD, id: 8, category_id: 3, field_type: 'boolean' }],
    };
    getAllCategories = mock(() => Promise.resolve([checklist]));
    getAllEntries = mock(() => Promise.resolve([]));
    const pending = deferred<Entry>();
    upsertChecklist = mock(() => pending.promise);
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    let toggled!: Promise<void>;
    act(() => {
      toggled = result.current.toggleField(checklist.id, 8);
    });
    readDayMode = mock(() => Promise.resolve(dayModeOf(NEXT_DAY)));
    await act(async () => {
      await result.current.reload();
    });
    expect(result.current.date).toBe(NEXT_DAY);

    await act(async () => {
      pending.resolve({ ...ENTRY, id: 30, category_id: checklist.id, entry_date: TODAY });
      await toggled;
    });

    expect(result.current.entries).toEqual([]);
  });

  it('drops the answer of an older snapshot that lands after a newer one', async () => {
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    const slowDay = deferred<ReturnType<typeof dayModeOf>>();
    readDayMode = mock(() => slowDay.promise);
    let older!: Promise<void>;
    act(() => {
      older = result.current.reload();
    });
    readDayMode = mock(() => Promise.resolve(dayModeOf(NEXT_DAY)));
    getAllEntries = mock(() => Promise.resolve([]));
    await act(async () => {
      await result.current.reload();
    });
    await act(async () => {
      await result.current.addNumber(CATEGORY.id, GLASSES_FIELD.id, 100);
    });
    expect(result.current.date).toBe(NEXT_DAY);
    expect(totalOf(result.current.entries)).toBe(100);

    await act(async () => {
      slowDay.resolve(dayModeOf(TODAY));
      await older;
    });

    expect(result.current.date).toBe(NEXT_DAY);
    expect(totalOf(result.current.entries)).toBe(100);
  });

  it('ignores the re-read of yesterday\'s records that returns after the day changed', async () => {
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    const slowRead = deferred<Entry[]>();
    getAllEntries = mock(() => slowRead.promise);
    let afterMark!: Promise<void>;
    act(() => {
      afterMark = result.current.reloadAfterMark(CATEGORY.id);
    });
    readDayMode = mock(() => Promise.resolve(dayModeOf(NEXT_DAY)));
    getAllEntries = mock(() => Promise.resolve([]));
    await act(async () => {
      await result.current.reload();
    });

    await act(async () => {
      slowRead.resolve([ENTRY]);
      await afterMark;
    });

    expect(result.current.entries).toEqual([]);
  });
});

describe('useToday.addNumber', () => {
  it('shows the increment before the request resolves', async () => {
    createEntry = mock(() => new Promise(() => {}));
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      void result.current.addNumber(CATEGORY.id, GLASSES_FIELD.id, 250);
    });

    expect(totalOf(result.current.entries)).toBe(250);
    expect(createEntry).toHaveBeenCalledWith({
      category_id: CATEGORY.id,
      entry_date: TODAY,
      values: [{ field_id: GLASSES_FIELD.id, value: '250' }],
    });
  });

  it('rolls back only the failed tap and keeps the successful ones', async () => {
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    let call = 0;
    createEntry = mock(() => {
      call += 1;
      return call === 2
        ? Promise.reject(new Error('server exploded'))
        : Promise.resolve(savedEntry(100 + call, 1));
    });

    await act(async () => {
      await Promise.all([
        result.current.addNumber(CATEGORY.id, GLASSES_FIELD.id, 1),
        result.current.addNumber(CATEGORY.id, GLASSES_FIELD.id, 1),
        result.current.addNumber(CATEGORY.id, GLASSES_FIELD.id, 1),
      ]);
    });

    expect(totalOf(result.current.entries)).toBe(2);
    expect(result.current.error).toBe('server exploded');
  });

  it('keeps an in-flight increment when a refetch lands mid-request', async () => {
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    const pendingCreate = deferred<Entry>();
    createEntry = mock(() => pendingCreate.promise);

    act(() => {
      void result.current.addNumber(CATEGORY.id, GLASSES_FIELD.id, 1);
    });
    expect(totalOf(result.current.entries)).toBe(1);

    // The refetch was answered by a server that had not seen the POST yet.
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await waitFor(() => expect(getAllEntries).toHaveBeenCalledTimes(2));
    expect(totalOf(result.current.entries)).toBe(1);

    await act(async () => {
      pendingCreate.resolve(savedEntry(11, 1));
      await Promise.resolve();
    });
    expect(totalOf(result.current.entries)).toBe(1);
  });

  it('counts a saved increment once after the refetch that returns it', async () => {
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.addNumber(CATEGORY.id, GLASSES_FIELD.id, 1);
    });
    expect(totalOf(result.current.entries)).toBe(1);

    getAllEntries = mock(() => Promise.resolve([ENTRY, savedEntry(11, 1)]));
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'));
    });

    await waitFor(() => expect(getAllEntries).toHaveBeenCalled());
    await waitFor(() => expect(totalOf(result.current.entries)).toBe(1));
  });

  it('takes the total from a refetch that saw another device write', async () => {
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    getAllEntries = mock(() => Promise.resolve([savedEntry(20, 3)]));
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'));
    });

    await waitFor(() => expect(totalOf(result.current.entries)).toBe(3));
  });
});

describe('useToday.deleteEntry', () => {
  it('withdraws the row before the delete reply arrives', async () => {
    const pendingDelete = deferred<void>();
    deleteEntry = mock(() => pendingDelete.promise);
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      void result.current.deleteEntry(ENTRY);
    });

    expect(result.current.entries).toEqual([]);
    expect(deleteEntry).toHaveBeenCalledWith(ENTRY.id);
    await act(async () => {
      pendingDelete.resolve();
      await Promise.resolve();
    });
  });

  it('restores exactly the deleted row when the server rejects it', async () => {
    deleteEntry = mock(() => Promise.reject(new Error('delete failed')));
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await expect(result.current.deleteEntry(ENTRY)).resolves.toBe(false);
    });

    expect(result.current.entries).toEqual([ENTRY]);
    expect(result.current.error).toBe('delete failed');
  });

  it('refuses to delete the local negative id of an in-flight quick add', async () => {
    const localEntry = { ...ENTRY, id: -1 };
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await expect(result.current.deleteEntry(localEntry)).resolves.toBe(false);
    });

    expect(deleteEntry).not.toHaveBeenCalled();
  });

  it('refreshes the avoid streak after its relapse entry is deleted', async () => {
    const avoidEntry: Entry = { ...ENTRY, category_id: SMOKING.id };
    const refreshed = {
      category_id: SMOKING.id,
      streak_mode: 'avoid' as const,
      current_streak: 4,
      best_streak: 9,
      last_relapse_date: null,
    };
    getAllCategories = mock(() => Promise.resolve([SMOKING]));
    getAllEntries = mock(() => Promise.resolve([avoidEntry]));
    getStreakApi = mock(() => Promise.resolve(refreshed));
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.streaksLoading).toBe(false));
    getStreakApi.mockClear();

    await act(async () => {
      await expect(result.current.deleteEntry(avoidEntry)).resolves.toBe(true);
    });

    expect(getStreakApi).toHaveBeenCalledWith(SMOKING.id);
    expect(result.current.streaks[SMOKING.id]).toEqual(refreshed);
  });
});

describe('useToday.toggleField', () => {
  it('replaces the day entry with the checklist response, so the list sees the new tick', async () => {
    const checklist: Category = {
      ...CATEGORY,
      id: 3,
      display_mode: 'checklist',
      fields: [{ ...GLASSES_FIELD, id: 8, category_id: 3, field_type: 'boolean' }],
    };
    const saved: Entry = {
      ...ENTRY,
      id: 30,
      category_id: checklist.id,
      values: [{ id: 31, entry_id: 30, field_id: 8, value: 'true' }],
    };
    getAllCategories = mock(() => Promise.resolve([checklist]));
    getAllEntries = mock(() => Promise.resolve([]));
    upsertChecklist = mock(() => Promise.resolve(saved));
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.toggleField(checklist.id, 8);
    });

    expect(result.current.entries).toEqual([saved]);
  });
});

describe('useToday.updateEntry', () => {
  it('restores the old row when the optimistic PATCH is rejected', async () => {
    const updateSpy = spyOn(entriesAPI, 'update').mockRejectedValue(new Error('update failed'));
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    try {
      await act(async () => {
        await expect(result.current.updateEntry(ENTRY, {
          entry_date: TODAY,
          values: [{ field_id: GLASSES_FIELD.id, value: '2' }],
        })).rejects.toThrow('update failed');
      });
      expect(result.current.entries).toEqual([ENTRY]);
      expect(result.current.error).toBe('update failed');
    } finally {
      updateSpy.mockRestore();
    }
  });
});


describe('useToday.tapQuickMark', () => {
  it('repaints from the tap\'s own answer, without asking the directory again', async () => {
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.quickMarks[0].today_total).toBeNull();

    const listCallsBefore = listQuickMarks.mock.calls.length;
    await act(async () => {
      await result.current.tapQuickMark(WATER_MARK.id);
    });

    expect(tapQuickMarkApi).toHaveBeenCalledTimes(1);
    expect(tapQuickMarkApi.mock.calls[0][0]).toBe(WATER_MARK.id);
    // One call per tap: the directory is not fetched again.
    expect(listQuickMarks.mock.calls.length).toBe(listCallsBefore);
    expect(result.current.quickMarks[0].today_total).toBe(250);
    expect(result.current.quickMarks[0].done).toBe(true);
  });

  it('shows the failure instead of a total that was never written', async () => {
    tapQuickMarkApi = mock(() => Promise.reject(new Error('server exploded')));
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.tapQuickMark(WATER_MARK.id);
    });

    expect(result.current.error).toBe('server exploded');
    expect(result.current.quickMarks[0].today_total).toBeNull();
    // Two attempts, then the failure is shown: the retry is one, not a loop.
    expect(tapQuickMarkApi).toHaveBeenCalledTimes(2);
  });

  it('has nothing to track when both the directory and the categories are empty', async () => {
    getAllCategories = mock(() => Promise.resolve([]));
    listQuickMarks = mock(() => Promise.resolve([]));
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.quickMarks).toEqual([]);
    expect(result.current.nothingToTrack).toBe(true);
  });

  it('has something to track when only the directory has rows', async () => {
    getAllCategories = mock(() => Promise.resolve([]));
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.nothingToTrack).toBe(false);
  });
});

describe('useToday quick-mark undo and retry', () => {
  it('sends the retry under the key of the first attempt, so the sum is not doubled', async () => {
    // The dropped send: the first attempt rejects the way a lost connection
    // does, the second succeeds. Both carry one key, which is what makes the
    // server treat them as one tap instead of two.
    let attempts = 0;
    tapQuickMarkApi = mock(() => {
      attempts += 1;
      return attempts === 1
        ? Promise.reject(new Error('network dropped'))
        : Promise.resolve(tapAnswer(250));
    });

    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.tapQuickMark(WATER_MARK.id);
    });

    expect(tapQuickMarkApi).toHaveBeenCalledTimes(2);
    const firstKey = tapQuickMarkApi.mock.calls[0][2];
    expect(typeof firstKey).toBe('string');
    expect(tapQuickMarkApi.mock.calls[1][2]).toBe(firstKey);
    // One tap's worth of water, not two, and no error left on the screen.
    expect(result.current.quickMarks[0].today_total).toBe(250);
    expect(result.current.error).toBeNull();
  });

  it('gives two taps two keys, so a second tap is a second tap', async () => {
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.tapQuickMark(WATER_MARK.id);
    });
    await act(async () => {
      await result.current.tapQuickMark(WATER_MARK.id);
    });

    expect(tapQuickMarkApi.mock.calls[0][2]).not.toBe(tapQuickMarkApi.mock.calls[1][2]);
  });

  it('offers the undo only after a tap, and takes the day back with one action', async () => {
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.lastQuickMarkEvent).toBeNull();

    await act(async () => {
      await result.current.tapQuickMark(WATER_MARK.id);
    });
    expect(result.current.lastQuickMarkEvent?.event_id).toBe(1);

    await act(async () => {
      await result.current.undoLastQuickMark();
    });

    expect(undoQuickMarkApi).toHaveBeenCalledTimes(1);
    expect(undoQuickMarkApi.mock.calls[0][0]).toBe(1);
    expect(result.current.quickMarks[0].today_total).toBe(0);
    expect(result.current.quickMarks[0].done).toBe(false);
    // The offer is spent: the tap it pointed at has been taken back.
    expect(result.current.lastQuickMarkEvent).toBeNull();
  });

  it('retires the offer and shows the reason when the server refuses the undo', async () => {
    undoQuickMarkApi = mock(() =>
      Promise.reject(new Error('the value was changed outside the journal'))
    );
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.tapQuickMark(WATER_MARK.id);
    });
    await act(async () => {
      await result.current.undoLastQuickMark();
    });

    expect(result.current.error).toBe('the value was changed outside the journal');
    expect(result.current.lastQuickMarkEvent).toBeNull();
    // Refused means untouched: the total the tap produced is still on screen.
    expect(result.current.quickMarks[0].today_total).toBe(250);
  });

  it('has nothing to undo when the request that failed wrote nothing', async () => {
    tapQuickMarkApi = mock(() => Promise.reject(new Error('server exploded')));
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.tapQuickMark(WATER_MARK.id);
    });
    await act(async () => {
      await result.current.undoLastQuickMark();
    });

    expect(result.current.lastQuickMarkEvent).toBeNull();
    expect(undoQuickMarkApi).not.toHaveBeenCalled();
  });
});

describe('useToday.reloadAfterMark', () => {
  const AFTER_TAP: Entry = savedEntry(12, 750);

  it('reads today\'s records again and shows them', async () => {
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.entries).toEqual([ENTRY]);
    getAllEntries = mock(() => Promise.resolve([ENTRY, AFTER_TAP]));

    await act(async () => {
      await result.current.reloadAfterMark(CATEGORY.id);
    });

    expect(getAllEntries).toHaveBeenCalledTimes(1);
    expect(result.current.entries).toEqual([ENTRY, AFTER_TAP]);
    expect(totalOf(result.current.entries)).toBe(750);
  });

  it('leaves the categories and the directory alone: a tap costs a read of the day, not of the screen', async () => {
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));
    const categoryReads = getAllCategories.mock.calls.length;
    const directoryReads = listQuickMarks.mock.calls.length;

    await act(async () => {
      await result.current.reloadAfterMark(CATEGORY.id);
    });

    expect(getAllCategories.mock.calls.length).toBe(categoryReads);
    expect(listQuickMarks.mock.calls.length).toBe(directoryReads);
  });

  it('reads the streak of an avoid category the tap belonged to, and shows it', async () => {
    const afterRelapse = {
      category_id: SMOKING.id,
      streak_mode: 'avoid' as const,
      current_streak: 0,
      best_streak: 9,
      last_relapse_date: TODAY,
    };
    getAllCategories = mock(() => Promise.resolve([CATEGORY, SMOKING]));
    getStreakApi = mock(() => Promise.resolve(afterRelapse));
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.streaksLoading).toBe(false));
    getStreakApi.mockClear();

    await act(async () => {
      await result.current.reloadAfterMark(SMOKING.id);
    });

    expect(getStreakApi).toHaveBeenCalledTimes(1);
    expect(getStreakApi).toHaveBeenCalledWith(SMOKING.id);
    expect(result.current.streaks[SMOKING.id]).toEqual(afterRelapse);
  });

  it('does not touch a streak when the tap belonged to a category without one', async () => {
    getAllCategories = mock(() => Promise.resolve([CATEGORY, SMOKING]));
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.streaksLoading).toBe(false));
    getStreakApi.mockClear();

    await act(async () => {
      await result.current.reloadAfterMark(CATEGORY.id);
    });

    expect(getStreakApi).not.toHaveBeenCalled();
  });

  it('moves the ticks of a checklist when a tick button flipped one', async () => {
    const checklist: Category = {
      ...CATEGORY,
      id: 3,
      display_mode: 'checklist',
      fields: [{ ...GLASSES_FIELD, id: 8, category_id: 3, field_type: 'boolean' }],
    };
    const ticked: Entry = {
      ...ENTRY,
      id: 20,
      category_id: checklist.id,
      values: [{ id: 21, entry_id: 20, field_id: 8, value: 'true' }],
    };
    getAllCategories = mock(() => Promise.resolve([checklist]));
    getAllEntries = mock(() => Promise.resolve([] as Entry[]));
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.checked[checklist.id][8]).toBe(false);
    getAllEntries = mock(() => Promise.resolve([ticked]));

    await act(async () => {
      await result.current.reloadAfterMark(checklist.id);
    });

    expect(result.current.checked[checklist.id][8]).toBe(true);
  });

  it('never lets an older answer land over a newer one', async () => {
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));
    const older = deferred<Entry[]>();
    const newer = deferred<Entry[]>();
    getAllEntries = mock()
      .mockImplementationOnce(() => older.promise)
      .mockImplementationOnce(() => newer.promise);

    let first!: Promise<void>;
    let second!: Promise<void>;
    act(() => {
      first = result.current.reloadAfterMark(CATEGORY.id);
      second = result.current.reloadAfterMark(CATEGORY.id);
    });
    await act(async () => {
      newer.resolve([savedEntry(14, 1000)]);
      await second;
    });
    await act(async () => {
      older.resolve([savedEntry(13, 500)]);
      await first;
    });

    expect(totalOf(result.current.entries)).toBe(1000);
  });

  it('keeps what was on screen and says so when the read fails', async () => {
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));
    getAllEntries = mock(() => Promise.reject(new Error('network down')));

    await act(async () => {
      await result.current.reloadAfterMark(CATEGORY.id);
    });

    expect(result.current.entries).toEqual([ENTRY]);
    expect(result.current.error).toBe('network down');
  });

  it('counts a saved increment once when the read returns it', async () => {
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.addNumber(CATEGORY.id, GLASSES_FIELD.id, 1);
    });
    const saved = savedEntry(11, 1);
    getAllEntries = mock(() => Promise.resolve([ENTRY, saved]));

    await act(async () => {
      await result.current.reloadAfterMark(CATEGORY.id);
    });

    expect(result.current.entries.filter((entry) => entry.id === 11)).toHaveLength(1);
    expect(totalOf(result.current.entries)).toBe(1);
  });
});

describe('the screen and its day-mode badge share one day (#247)', () => {
  const NEXT_DAY = '2026-07-25';

  function renderBoth() {
    return renderHook(() => {
      const today = useToday();
      const badge = useDayMode(today.dayModeClient);
      useTodayDayModeSync(today, badge);
      return { today, badge };
    });
  }

  it('asks the server for the day once on mount, for the header and the badge together', async () => {
    const { result } = renderBoth();
    await waitFor(() => expect(result.current.today.loading).toBe(false));
    await waitFor(() => expect(result.current.badge.mode).not.toBeNull());

    expect(readDayMode).toHaveBeenCalledTimes(1);
    expect(result.current.badge.mode?.date).toBe(result.current.today.date);
  });

  it('names one day in the header and the badge when the day changes between the two reads', async () => {
    const { result } = renderBoth();
    await waitFor(() => expect(result.current.badge.mode).not.toBeNull());

    // Two requests would hear two answers: the first one the new day, the second one the old.
    const answers = [NEXT_DAY, TODAY];
    readDayMode = mock(() => Promise.resolve(dayModeOf(answers.shift() ?? TODAY)));
    getAllEntries = mock(() => Promise.resolve([]));
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await waitFor(() => expect(result.current.today.date).toBe(NEXT_DAY));
    await waitFor(() => expect(result.current.badge.mode?.date).toBe(NEXT_DAY));

    expect(readDayMode).toHaveBeenCalledTimes(1);
  });

  it('moves the screen to the day the badge heard when no snapshot is on the way', async () => {
    const { result } = renderBoth();
    await waitFor(() => expect(result.current.badge.mode).not.toBeNull());

    readDayMode = mock(() => Promise.resolve(dayModeOf(NEXT_DAY)));
    getAllEntries = mock(() => Promise.resolve([]));
    await act(async () => {
      await result.current.badge.reload();
    });

    await waitFor(() => expect(result.current.today.date).toBe(NEXT_DAY));
  });

  it('does not add requests per screen: a return to the tab is one day read, one records read', async () => {
    const { result } = renderBoth();
    await waitFor(() => expect(result.current.badge.mode).not.toBeNull());
    readDayMode.mockClear();
    getAllEntries.mockClear();

    act(() => {
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await waitFor(() => expect(getAllEntries).toHaveBeenCalledTimes(1));

    expect(readDayMode).toHaveBeenCalledTimes(1);
  });
});

describe('a day the server does not confirm (#253)', () => {
  const NEXT_DAY = '2026-07-25';
  const CHECKLIST: Category = {
    ...CATEGORY,
    id: 3,
    display_mode: 'checklist',
    fields: [{ ...GLASSES_FIELD, id: 8, category_id: 3, field_type: 'boolean' }],
  };

  afterEach(() => {
    jest.useRealTimers();
  });

  async function tick(times: number) {
    for (let i = 0; i < times; i += 1) {
      await act(async () => {
        jest.advanceTimersByTime(DAY_RECHECK_MS);
      });
    }
  }

  it('says the day is not followed after the third failed minute read, and refuses to write', async () => {
    jest.useFakeTimers();
    getAllCategories = mock(() => Promise.resolve([CATEGORY, CHECKLIST]));
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    readDayMode = mock(() => Promise.reject(new Error('offline')));
    await tick(DAY_POLL_FAILURES_LIMIT - 1);
    expect(result.current.dayStale).toBe(false);
    expect(result.current.error).toBeNull();
    await tick(1);
    expect(result.current.dayStale).toBe(true);
    expect(result.current.error).toBe(DAY_UNCONFIRMED);

    let added = true;
    await act(async () => {
      await result.current.toggleField(CHECKLIST.id, 8);
      added = await result.current.addNumber(CATEGORY.id, GLASSES_FIELD.id, 250);
    });
    expect(added).toBe(false);
    expect(upsertChecklist).not.toHaveBeenCalled();
    expect(createEntry).not.toHaveBeenCalled();
    expect(isFieldChecked(result.current.checked, CHECKLIST.id, 8)).toBe(false);
  });

  it('writes again, and withdraws its own banner, once a read goes through', async () => {
    jest.useFakeTimers();
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));
    readDayMode = mock(() => Promise.reject(new Error('offline')));
    await tick(DAY_POLL_FAILURES_LIMIT);
    expect(result.current.dayStale).toBe(true);

    readDayMode = mock(() => Promise.resolve(dayModeOf(TODAY)));
    await tick(1);
    expect(result.current.dayStale).toBe(false);
    expect(result.current.error).toBeNull();

    await act(async () => {
      await result.current.addNumber(CATEGORY.id, GLASSES_FIELD.id, 250);
    });
    expect(createEntry).toHaveBeenCalledTimes(1);
  });

  it('does not bring a banner the user closed back with every minute', async () => {
    jest.useFakeTimers();
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));
    readDayMode = mock(() => Promise.reject(new Error('offline')));
    await tick(DAY_POLL_FAILURES_LIMIT);
    expect(result.current.error).toBe(DAY_UNCONFIRMED);

    act(() => result.current.setError(null));
    await tick(3);

    expect(result.current.error).toBeNull();
  });

  it('refuses to write after a full snapshot could not confirm the day it knew', async () => {
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    readDayMode = mock(() => Promise.reject(new Error('offline')));
    await act(async () => {
      await result.current.reload();
    });
    expect(result.current.dayStale).toBe(true);

    let added = true;
    await act(async () => {
      added = await result.current.addNumber(CATEGORY.id, GLASSES_FIELD.id, 250);
    });
    expect(added).toBe(false);
    expect(createEntry).not.toHaveBeenCalled();
  });

  it('retries a failed first load every minute without raising the closed banner again', async () => {
    jest.useFakeTimers();
    readDayMode = mock(() => Promise.reject(new Error('day unknown')));
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.error).toBe('day unknown'));

    act(() => result.current.setError(null));
    await tick(2);
    expect(readDayMode.mock.calls.length).toBeGreaterThanOrEqual(3);
    expect(result.current.error).toBeNull();

    readDayMode = mock(() => Promise.resolve(dayModeOf(TODAY)));
    await tick(1);
    await waitFor(() => expect(result.current.date).toBe(TODAY));
  });

  it('starts no snapshot from a minute read that is answered after the screen is gone', async () => {
    jest.useFakeTimers();
    const { result, unmount } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    const slowDay = deferred<ReturnType<typeof dayModeOf>>();
    readDayMode = mock(() => slowDay.promise);
    await tick(1);
    getAllCategories.mockClear();
    unmount();
    await act(async () => {
      slowDay.resolve(dayModeOf(NEXT_DAY));
      await Promise.resolve();
    });

    expect(getAllCategories).not.toHaveBeenCalled();
  });

  it('leaves the map of the new day alone when a tick of the old day fails', async () => {
    getAllCategories = mock(() => Promise.resolve([CHECKLIST]));
    getAllEntries = mock(() => Promise.resolve([]));
    const pending = deferred<Entry>();
    upsertChecklist = mock(() => pending.promise);
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    let toggled!: Promise<void>;
    act(() => {
      toggled = result.current.toggleField(CHECKLIST.id, 8);
    });
    // The new day already has this field ticked, by another device.
    readDayMode = mock(() => Promise.resolve(dayModeOf(NEXT_DAY)));
    getAllEntries = mock(() =>
      Promise.resolve([
        {
          ...ENTRY,
          id: 31,
          category_id: CHECKLIST.id,
          entry_date: NEXT_DAY,
          values: [{ id: 1, entry_id: 31, field_id: 8, value: 'true' }],
        },
      ])
    );
    await act(async () => {
      await result.current.reload();
    });
    expect(isFieldChecked(result.current.checked, CHECKLIST.id, 8)).toBe(true);

    await act(async () => {
      pending.reject(new Error('save failed'));
      await toggled;
    });

    expect(isFieldChecked(result.current.checked, CHECKLIST.id, 8)).toBe(true);
  });
});

describe('round 2: the badge follows the day the screen moved to (#247)', () => {
  const NEXT_DAY = '2026-07-25';

  afterEach(() => {
    jest.useRealTimers();
  });

  async function tick(times: number) {
    for (let i = 0; i < times; i += 1) {
      await act(async () => {
        jest.advanceTimersByTime(DAY_RECHECK_MS);
      });
    }
  }

  function renderBoth() {
    return renderHook(() => {
      const today = useToday();
      const badge = useDayMode(today.dayModeClient);
      useTodayDayModeSync(today, badge);
      return { today, badge };
    });
  }

  it('moves the badge to the day the minute timer found, and a decision goes to that day', async () => {
    jest.useFakeTimers();
    const { result } = renderBoth();
    await waitFor(() => expect(result.current.badge.mode?.date).toBe(TODAY));

    readDayMode = mock(() => Promise.resolve(dayModeOf(NEXT_DAY)));
    getAllEntries = mock(() => Promise.resolve([]));
    await tick(1);
    await waitFor(() => expect(result.current.today.date).toBe(NEXT_DAY));
    await waitFor(() => expect(result.current.badge.mode?.date).toBe(NEXT_DAY));

    await act(async () => {
      await result.current.badge.decide('dayoff', false);
    });
    expect(writeDayMode).toHaveBeenCalledTimes(1);
    expect(writeDayMode.mock.calls[0][0]).toBe(NEXT_DAY);
  });

  it('moves the badge to the day an explicit reload found', async () => {
    const { result } = renderBoth();
    await waitFor(() => expect(result.current.badge.mode?.date).toBe(TODAY));

    readDayMode = mock(() => Promise.resolve(dayModeOf(NEXT_DAY)));
    getAllEntries = mock(() => Promise.resolve([]));
    await act(async () => {
      await result.current.today.reload();
    });

    await waitFor(() => expect(result.current.badge.mode?.date).toBe(NEXT_DAY));
  });

  it('locks the badge when the day is not confirmed, so it cannot write to the old day', async () => {
    jest.useFakeTimers();
    const { result } = renderBoth();
    await waitFor(() => expect(result.current.badge.mode?.date).toBe(TODAY));

    readDayMode = mock(() => Promise.reject(new Error('offline')));
    await tick(DAY_POLL_FAILURES_LIMIT);
    await waitFor(() => expect(result.current.today.dayStale).toBe(true));
    await waitFor(() => expect(result.current.badge.loadFailed).toBe(true));

    await act(async () => {
      await result.current.badge.decide('dayoff', false);
    });
    expect(writeDayMode).not.toHaveBeenCalled();
  });

  it('counts a read of the day that never answers as a failed minute read', async () => {
    jest.useFakeTimers();
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    readDayMode = mock(() => new Promise(() => {}));
    // The first tick starts the read that hangs, each later one finds it unanswered.
    await tick(DAY_POLL_FAILURES_LIMIT);
    expect(result.current.dayStale).toBe(false);
    await tick(1);

    expect(result.current.dayStale).toBe(true);
    expect(readDayMode.mock.calls.length).toBeGreaterThanOrEqual(DAY_POLL_FAILURES_LIMIT);
  });

  it('starts one snapshot, not two, when a tick joins the read of a snapshot on its way', async () => {
    jest.useFakeTimers();
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));
    getAllCategories.mockClear();

    const pendingDay = deferred<ReturnType<typeof dayModeOf>>();
    readDayMode = mock(() => pendingDay.promise);
    getAllEntries = mock(() => Promise.resolve([]));
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await tick(1);
    await act(async () => {
      pendingDay.resolve(dayModeOf(NEXT_DAY));
      await Promise.resolve();
    });
    await waitFor(() => expect(result.current.date).toBe(NEXT_DAY));

    expect(getAllCategories).toHaveBeenCalledTimes(1);
  });

  it('joins the day read in flight for the badge, and starts a new request for a retry after a lost read', async () => {
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    const hung = deferred<ReturnType<typeof dayModeOf>>();
    readDayMode = mock(() => hung.promise);
    void result.current.dayModeClient.read();
    void result.current.dayModeClient.read();
    expect(readDayMode).toHaveBeenCalledTimes(1);

    void result.current.dayModeClient.read({ fresh: true });
    expect(readDayMode).toHaveBeenCalledTimes(2);
    hung.resolve(dayModeOf(TODAY));
    await act(async () => {
      await Promise.resolve();
    });
  });

  it('starts no snapshot from a badge read answered after the screen is gone', async () => {
    const { result, unmount } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));
    getAllCategories.mockClear();

    const slowDay = deferred<ReturnType<typeof dayModeOf>>();
    readDayMode = mock(() => slowDay.promise);
    const badgeRead = result.current.dayModeClient.read();
    unmount();
    await act(async () => {
      slowDay.resolve(dayModeOf(NEXT_DAY));
      await badgeRead;
    });

    expect(getAllCategories).not.toHaveBeenCalled();
  });
});

describe('round 2: a full page of the records window is read exactly (#247)', () => {
  it('asks the window with an explicit page size', async () => {
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(getAllEntries.mock.calls[0][0]).toMatchObject({ limit: WINDOW_LIMIT });
  });

  it('reads the day exactly when the window came back full, and shows only that read', async () => {
    const full = Array.from({ length: WINDOW_LIMIT }, (_, index) => ({
      ...ENTRY,
      id: 1000 + index,
      entry_date: TODAY,
    }));
    getAllEntries = mock((params: { limit?: number }) =>
      Promise.resolve(params.limit === WINDOW_LIMIT ? full : [ENTRY])
    );
    const { result } = renderHook(() => useToday());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(getAllEntries).toHaveBeenCalledTimes(2);
    expect(getAllEntries).toHaveBeenLastCalledWith({ startDate: TODAY, endDate: TODAY });
    expect(result.current.entries).toEqual([ENTRY]);
  });
});
