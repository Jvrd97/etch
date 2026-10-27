// [review:need-review] PHASE-01/61-today-total-owned-by-hook, PHASE-03/121, PHASE-03/124, PHASE-03/123, PHASE-01/177, PHASE-01/206, PHASE-03/237
// summary: tests for useToday — the targeted re-read after a quick mark (records, ticks and the one streak that can have moved, nothing else, and never an older answer over a newer one), silent visibility refetch, the two rounds of the cold path (the buttons land after the first, the streaks report themselves from the second and a tap goes through while they are still in flight), the optimistic number increment with per-tap rollback, the quick-mark tap that costs one request and repaints from its own answer, the retry that sends the second attempt under the key of the first, and the undo that puts the day back
// summary: the server day in useToday: the header, the records read, the re-read after a mark, the checklist tick and the increment use the day of GET /day-mode while the browser is a day behind; a changed day is followed on return to the tab; a day that cannot be read leaves no screen

import { afterEach, beforeEach, describe, expect, it, mock, spyOn } from 'bun:test';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import type {
  Category,
  Entry,
  Field,
  QuickMark,
  QuickMarkEvent,
  QuickMarkUndo,
} from '@/lib/api';
import { numberFieldSum } from '@/lib/today-entries';

const TIMESTAMP = '2026-07-24T00:00:00Z';
const TODAY = '2026-07-24';
// The day the browser believes it is: a zone behind the server (Pacific/Pago_Pago
// at 23:00 UTC), or 00:30 before the boundary hour. Never the server's day, so
// any read of the browser clock shows up as a different date in a request.
const BROWSER_DAY = '2026-07-23';

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
function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

let getAllCategories: ReturnType<typeof mock>;
let getAllEntries: ReturnType<typeof mock>;
let readDayMode: ReturnType<typeof mock>;
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

mock.module('@/lib/date', () => ({ todayISO: () => BROWSER_DAY }));

const { useToday, STREAKS_FAILED } = await import('./useToday');
const { entriesAPI } = await import('@/lib/api');

beforeEach(() => {
  getAllCategories = mock(() => Promise.resolve([CATEGORY]));
  getAllEntries = mock(() => Promise.resolve([ENTRY]));
  readDayMode = mock(() => Promise.resolve(dayModeOf(TODAY)));
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
    expect(getAllEntries).toHaveBeenCalledWith({ startDate: TODAY, endDate: TODAY });
    // The header, the records and the buttons all say the same date.
    expect(result.current.quickMarks.map((mark) => mark.entry_date)).toEqual([TODAY]);
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

    expect(getAllEntries).toHaveBeenCalledWith({ startDate: NEXT_DAY, endDate: NEXT_DAY });
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
    expect(getAllEntries).not.toHaveBeenCalledWith({ startDate: BROWSER_DAY, endDate: BROWSER_DAY });
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
