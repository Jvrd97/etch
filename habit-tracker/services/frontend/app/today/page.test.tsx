// [review:need-review] PHASE-03/162, PHASE-03/237, PHASE-03/247, PHASE-03/257
// summary: tests for the desktop Today screen — the day-mode badge is drawn from the day-mode read, and is locked (aria-disabled, aria-busy) exactly while the hook reads the day
// summary: the desktop Today shows one server date in the title, the records read, the obligation count and the entry form while the browser clock is a day behind; with an unknown day there is no date line, no «nothing to track» and the ask-about-the-day button is disabled
// [review:need-review] PHASE-03/121, PHASE-01/177, PHASE-01/206, #311
// summary: #311 — a tap is drawn on the button before the server answers, and a refused tap is taken off and said under the row
// summary: tests for the desktop Today screen — the quick-mark section drawn from the directory, absent entirely when the directory is empty, and the legacy quick-input card that steps aside for a category the directory covers, and the sets behind a quick-mark card — the dialog of every set opened from the card's name and counter, the plus and the key that still add one without opening it, the day's records read again after every tap, and a set taken back from the list lowering the card's counter

import { afterEach, beforeEach, describe, expect, it, mock, setSystemTime } from 'bun:test';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import type { Category, Entry, QuickMark, QuickMarkDayEvent } from '@/lib/api';

const TIMESTAMP = '2026-07-30T00:00:00Z';

/** One number category, so Today has a quick-input row and is not the empty state. */
const NUTRITION: Category = {
  id: 5,
  name: 'Питание',
  display_mode: 'form',
  streak_mode: 'build',
  is_active: true,
  show_in_today: true,
  created_at: TIMESTAMP,
  updated_at: TIMESTAMP,
  fields: [
    {
      id: 9,
      category_id: 5,
      name: 'Калории',
      field_type: 'number',
      is_required: false,
      order: 0,
      created_at: TIMESTAMP,
      updated_at: TIMESTAMP,
    },
  ],
};

/** One button of the directory, over the same category the screen shows. */
const WATER_MARK: QuickMark = {
  id: 3,
  label: '+250 мл',
  category_id: NUTRITION.id,
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
  entry_date: '2026-07-30',
  today_total: null,
  done: false,
  planned: false,
  plan_item_id: null,
};

/** The mode the stub of the server answers for any date: a working no-code day by the schedule. */
const TUESDAY_MODE = { date: '2026-07-30', kind: 'work', nocode: true, source: 'schedule' };

/** A running obligation whose day is still waiting for a verdict. */
const WATER_CHALLENGE = {
  id: 4,
  title: '7 дней подряд ≥ 2 л воды',
  category_id: 5,
  field_id: 9,
  rule_kind: 'metric_at_least',
  target: '2.000',
  starts_on: '2026-07-28',
  ends_on: '2026-08-03',
  failure_mode: 'any_miss',
  allowed_misses: 0,
  status: 'active',
  origin: 'human',
  failed_on: null,
  total_days: 7,
  day_number: 3,
  done_count: 2,
  misses_used: 0,
  misses_left: 0,
  today_verdict: 'pending',
  created_at: '2026-07-28T06:00:00Z',
};

let getCategories: ReturnType<typeof mock>;
let getEntries: ReturnType<typeof mock>;
let readDayMode: ReturnType<typeof mock>;
let listChallenges: ReturnType<typeof mock>;
let setDayVerdict: ReturnType<typeof mock>;
let listQuickMarks: ReturnType<typeof mock>;
let tapQuickMark: ReturnType<typeof mock>;
let undoQuickMark: ReturnType<typeof mock>;
let dayEvents: ReturnType<typeof mock>;

// Declares the whole @/lib/api surface: bun fixes a module's export names the
// first time anything links against it and shares that registry across the run.
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
  // Тренировка (#92). Есть в каждом моке api по причине, названной выше.
  trainingAPI: {
    getState: () => Promise.resolve(null),
    setProgression: () => Promise.resolve(null),
    complaints: () => Promise.resolve([]),
    openComplaint: () => Promise.resolve(null),
    closeComplaint: () => Promise.resolve(null),
    records: () => Promise.resolve([]),
  },
  // Обязательства (#127). Есть в каждом моке api по причине, названной выше.
  challengesAPI: {
    list: () => listChallenges(),
    get: () => Promise.resolve(null),
    create: () => Promise.resolve(null),
    patch: () => Promise.resolve(null),
    recompute: () => Promise.resolve(null),
    setDayVerdict: (id: number, day: string, draft: unknown) => setDayVerdict(id, day, draft),
  },
  // Чат (#111). Есть в каждом моке api по причине, названной выше.
  chatAPI: {
    list: () => Promise.resolve([]),
    create: () => Promise.resolve(null),
    get: () => Promise.resolve(null),
    reset: () => Promise.resolve({ reset: 0 }),
    context: () => Promise.resolve(null),
    remove: () => Promise.resolve({}),
    getPlan: () => Promise.resolve(null),
    applyPlan: () => Promise.resolve(null),
    dismissPlan: () => Promise.resolve(undefined),
    streamMessage: () => Promise.resolve(undefined),
  },
  quickMarksAPI: {
    list: () => listQuickMarks(),
    tap: (id: number) => tapQuickMark(id),
    undo: (eventId: number) => undoQuickMark(eventId),
    dayEvents: (categoryId: number) => dayEvents(categoryId),
    sources: () => Promise.resolve([]),
  },
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
    getAll: () => getCategories(),
    getById: () => Promise.resolve(null),
    getStreak: () => Promise.resolve(null),
    create: () => Promise.resolve(null),
    update: () => Promise.resolve(null),
    delete: () => Promise.resolve(undefined),
    addField: () => Promise.resolve(null),
    applyBatch: () => Promise.resolve({ categories: [], fields: [] }),
  },
  entriesAPI: {
    getAll: (params?: unknown) => getEntries(params),
    create: () => Promise.resolve(null),
    update: () => Promise.resolve(null),
    delete: () => Promise.resolve(undefined),
    upsertChecklist: () => Promise.resolve({}),
  },
  tableAPI: { get: () => Promise.resolve({ days: [] }) },
  journalAPI: { getAll: () => Promise.resolve({ total: 0, items: [] }) },
}));

mock.module('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
  usePathname: () => '/today',
  useRouter: () => ({ push: () => {}, replace: () => {} }),
}));

const { default: TodayPage } = await import('./page');
const { TAP_FAILED } = await import('@/hooks/useQuickMarks');

/** Render Today and let its catalogue, entries and directory requests settle. */
async function renderToday() {
  render(<TodayPage />);
  await waitFor(() => expect(screen.getByText('Today')).toBeDefined());
}

beforeEach(() => {
  getCategories = mock(() => Promise.resolve([NUTRITION]));
  getEntries = mock(() => Promise.resolve([] as Entry[]));
  readDayMode = mock(() => Promise.resolve(TUESDAY_MODE));
  listChallenges = mock(() => Promise.resolve([]));
  setDayVerdict = mock(() => Promise.resolve(null));
  listQuickMarks = mock(() => Promise.resolve([] as QuickMark[]));
  tapQuickMark = mock(() =>
    Promise.resolve({
      event_id: 1,
      quick_mark_id: WATER_MARK.id,
      entry_id: 5,
      entry_date: WATER_MARK.entry_date,
      occurred_at: TIMESTAMP,
      today_total: 250,
      done: true,
      planned: false,
      plan_item_id: null,
    })
  );
  undoQuickMark = mock(() => Promise.resolve(null));
  dayEvents = mock(() => Promise.resolve([] as QuickMarkDayEvent[]));
});

afterEach(() => {
  cleanup();
});

describe('the quick marks of /today', () => {
  it('opens without a quick-mark section when the directory is empty', async () => {
    await renderToday();

    expect(screen.queryByText('Быстрые отметки')).toBeNull();
    expect(screen.queryByRole('button', { name: WATER_MARK.label })).toBeNull();
  });

  it('draws the buttons the directory returned', async () => {
    listQuickMarks = mock(() => Promise.resolve([WATER_MARK]));
    await renderToday();

    expect(screen.getByText('Быстрые отметки')).toBeDefined();
    expect(screen.getByRole('button', { name: WATER_MARK.label })).toBeDefined();
  });

  it('sends the button id on a tap and repaints from the answer', async () => {
    listQuickMarks = mock(() => Promise.resolve([WATER_MARK]));
    await renderToday();

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: WATER_MARK.label }));
    });

    expect(tapQuickMark).toHaveBeenCalledTimes(1);
    expect(tapQuickMark.mock.calls[0][0]).toBe(WATER_MARK.id);
    expect(screen.getByText('250 мл')).toBeDefined();
  });

  it('draws the tap on the button before the server answers', async () => {
    listQuickMarks = mock(() => Promise.resolve([WATER_MARK]));
    tapQuickMark = mock(() => new Promise(() => {}));
    await renderToday();

    act(() => {
      fireEvent.click(screen.getByRole('button', { name: WATER_MARK.label }));
    });

    expect(screen.getByText('250 мл')).toBeDefined();
  });

  it('takes a refused tap off the button and says so under the row', async () => {
    listQuickMarks = mock(() => Promise.resolve([WATER_MARK]));
    tapQuickMark = mock(() => Promise.reject(new TypeError('Failed to fetch')));
    await renderToday();

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: WATER_MARK.label }));
    });

    expect(screen.queryByText('250 мл')).toBeNull();
    expect(within(screen.getByRole('alert')).getByText(TAP_FAILED)).toBeDefined();
  });

  it('drops the legacy quick-input card of a category the directory covers', async () => {
    listQuickMarks = mock(() => Promise.resolve([WATER_MARK]));
    await renderToday();

    expect(screen.queryByLabelText('Питание: add Калории')).toBeNull();
  });

  it('keeps the card of a category the directory does not cover', async () => {
    await renderToday();

    expect(screen.getByLabelText('Питание: add Калории')).toBeDefined();
  });

  it('opens the category day list from the card without treating a plus as a card tap', async () => {
    getEntries = mock(() => Promise.resolve([
      {
        id: 12, category_id: NUTRITION.id, entry_date: '2026-07-30',
        created_at: '2026-07-30T09:12:00Z', updated_at: TIMESTAMP,
        values: [{ id: 13, entry_id: 12, field_id: 9, value: '300' }],
      },
    ]));
    await renderToday();

    fireEvent.click(screen.getByRole('button', { name: "Open today's Питание entry" }));
    expect(screen.getByRole('heading', { name: 'Питание — сегодня' })).toBeDefined();
    expect(screen.getByText('Калории 300')).toBeDefined();
  });
});

/** A set the journal holds for the water button, `undoable` only when it is the last. */
function waterSet(eventId: number, at: string, undoable = false): QuickMarkDayEvent {
  return {
    event_id: eventId,
    quick_mark_id: WATER_MARK.id,
    label: WATER_MARK.label,
    kind: 'increment',
    unit_label: 'мл',
    entry_date: WATER_MARK.entry_date,
    occurred_at: at,
    delta: 250,
    bool_value: null,
    undone_at: null,
    undoable,
  };
}

const OPEN_WATER_SETS = 'Подходы за сегодня — +250 мл';

function fiveSets(): QuickMarkDayEvent[] {
  return [1, 2, 3, 4, 5].map((n) => waterSet(n, `2026-07-30T0${n}:00:00Z`, n === 5));
}

describe('the day mode on /today', () => {
  it('draws the mode of the day with who decided it', async () => {
    await renderToday();

    await waitFor(() => expect(screen.getByLabelText('Вид дня')).toBeDefined());
    expect((screen.getByLabelText('no-code') as HTMLInputElement).checked).toBe(true);
    expect(screen.getByText('по расписанию')).toBeDefined();
  });

  it('locks the badge with aria-disabled while the day is read again, and frees it when the read answers', async () => {
    await renderToday();
    const select = await screen.findByLabelText('Вид дня');
    expect(select.getAttribute('aria-disabled')).toBe('false');

    // The window is focused again: the second read of the day does not answer yet.
    let answer: (mode: typeof TUESDAY_MODE) => void = () => {};
    readDayMode = mock(
      () =>
        new Promise<typeof TUESDAY_MODE>((resolve) => {
          answer = resolve;
        })
    );
    select.focus();
    act(() => {
      window.dispatchEvent(new Event('focus'));
    });

    await waitFor(() => expect(screen.getByLabelText('Вид дня').getAttribute('aria-disabled')).toBe('true'));
    expect(screen.getByLabelText('Вид дня').closest('[aria-busy]')?.getAttribute('aria-busy')).toBe('true');
    // A locked control stays enabled for the browser, so the keyboard focus is not lost.
    expect((screen.getByLabelText('Вид дня') as HTMLSelectElement).disabled).toBe(false);
    expect(document.activeElement).toBe(screen.getByLabelText('Вид дня'));

    await act(async () => {
      answer(TUESDAY_MODE);
    });
    await waitFor(() => expect(screen.getByLabelText('Вид дня').getAttribute('aria-disabled')).toBe('false'));
  });
});

describe('the day of /today comes from the server', () => {
  afterEach(() => {
    setSystemTime();
  });

  it('shows one date in the title, the records read and the buttons while the browser is a day behind', async () => {
    // Local noon of the 29th: the browser says 07-29, the server runs 07-30.
    setSystemTime(new Date(2026, 6, 29, 12, 0, 0));
    listQuickMarks = mock(() => Promise.resolve([WATER_MARK]));
    await renderToday();

    expect(screen.getByText(/^2026-07-30 — /)).toBeDefined();
    // The records are asked for a window around the browser's day and cut to the server's, or read
    // exactly when the server's day is outside it: the read that supplies them holds the server's day.
    const [params] = getEntries.mock.calls.at(-1) ?? [];
    expect(params.startDate <= '2026-07-30' && '2026-07-30' <= params.endDate).toBe(true);
    expect(screen.getByRole('button', { name: WATER_MARK.label })).toBeDefined();
  });

  it('asks the server for its day once for the title and the day-mode badge together', async () => {
    // A second read could hear another day around the boundary: the badge would then
    // decide a day the title does not show.
    setSystemTime(new Date(2026, 6, 29, 12, 0, 0));
    await renderToday();
    await waitFor(() => expect(screen.getByLabelText('Вид дня')).toBeDefined());

    expect(readDayMode).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/^2026-07-30 — /)).toBeDefined();
  });

  it('starts a new obligation on the server date and ends it a week later, in any zone', async () => {
    // Local noon of the 29th: the browser says 07-29 in any zone, the server runs 07-30.
    setSystemTime(new Date(2026, 6, 29, 12, 0, 0));
    await renderToday();

    fireEvent.click(await screen.findByRole('button', { name: 'Новый' }));

    expect((screen.getByLabelText('Начало') as HTMLInputElement).value).toBe('2026-07-30');
    expect((screen.getByLabelText('Конец') as HTMLInputElement).value).toBe('2026-08-05');
  });

  it('counts a day of an obligation by the server date, not the browser one', async () => {
    setSystemTime(new Date(2026, 6, 29, 12, 0, 0));
    listChallenges = mock(() => Promise.resolve([WATER_CHALLENGE]));
    await renderToday();

    await act(async () => {
      fireEvent.click(await screen.findByText('Засчитать день'));
    });

    expect(setDayVerdict).toHaveBeenCalledWith(WATER_CHALLENGE.id, '2026-07-30', { verdict: 'done' });
  });

  it('opens the entry form of a card on the server date, not the browser one', async () => {
    setSystemTime(new Date(2026, 6, 29, 12, 0, 0));
    await renderToday();

    fireEvent.click(screen.getByRole('button', { name: "Open today's Питание entry" }));
    fireEvent.click(screen.getByRole('button', { name: 'Add entry' }));

    const dateInput = document.querySelector('input[type="date"]') as HTMLInputElement;
    expect(dateInput.value).toBe('2026-07-30');
  });

  it('says the day is unknown when the server cannot name it, instead of an empty date', async () => {
    readDayMode = mock(() => Promise.reject(new Error('day unknown')));
    await renderToday();

    expect(await screen.findByText('day unknown')).toBeDefined();
    expect(screen.queryByText(/one tap to check things off/)).toBeNull();
    // Nothing was read, so "nothing to track" would be a claim the screen cannot make.
    expect(screen.queryByText('Nothing to track today')).toBeNull();
    expect(
      (screen.getByRole('button', { name: 'Спросить про день' }) as HTMLButtonElement).disabled
    ).toBe(true);
  });
});

describe('the sets behind a quick-mark card on /today', () => {
  it('opens the dialog with every set from the name and counter of the card', async () => {
    listQuickMarks = mock(() => Promise.resolve([{ ...WATER_MARK, today_total: 1250, done: true }]));
    dayEvents = mock(() => Promise.resolve(fiveSets()));
    await renderToday();

    fireEvent.click(screen.getByRole('button', { name: OPEN_WATER_SETS }));

    expect(screen.getByRole('heading', { name: 'Питание — сегодня' })).toBeDefined();
    const sets = await screen.findByRole('list', { name: 'Подходы за сегодня' });
    await waitFor(() => expect(within(sets).getAllByRole('listitem').length).toBe(5));
    expect(dayEvents.mock.calls[0][0]).toBe(NUTRITION.id);
    expect(screen.getByText('Итого за день: 1250 мл')).toBeDefined();
  });

  it('keeps the plus adding a set without opening anything', async () => {
    listQuickMarks = mock(() => Promise.resolve([WATER_MARK]));
    await renderToday();

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: WATER_MARK.label }));
    });

    expect(tapQuickMark).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('heading', { name: 'Питание — сегодня' })).toBeNull();
    expect(dayEvents).not.toHaveBeenCalled();
  });

  it('keeps the card of a category without a quick mark opening the plain list', async () => {
    getEntries = mock(() =>
      Promise.resolve([
        {
          id: 12, category_id: NUTRITION.id, entry_date: '2026-07-30',
          created_at: '2026-07-30T09:12:00Z', updated_at: TIMESTAMP,
          values: [{ id: 13, entry_id: 12, field_id: 9, value: '300' }],
        },
      ])
    );
    await renderToday();

    fireEvent.click(screen.getByRole('button', { name: "Open today's Питание entry" }));

    expect(screen.getByText('Калории 300')).toBeDefined();
    expect(screen.queryByRole('list', { name: 'Подходы за сегодня' })).toBeNull();
    expect(dayEvents).not.toHaveBeenCalled();
  });

  it('lowers the counter of the card when the last set is taken back from the list', async () => {
    listQuickMarks = mock(() => Promise.resolve([{ ...WATER_MARK, today_total: 1250, done: true }]));
    dayEvents = mock(() => Promise.resolve(fiveSets()));
    undoQuickMark = mock(() =>
      Promise.resolve({
        event_id: 5,
        quick_mark_id: WATER_MARK.id,
        entry_date: WATER_MARK.entry_date,
        undone_at: TIMESTAMP,
        today_total: 1000,
        done: true,
      })
    );
    await renderToday();
    fireEvent.click(screen.getByRole('button', { name: OPEN_WATER_SETS }));
    const sets = await screen.findByRole('list', { name: 'Подходы за сегодня' });
    await waitFor(() => expect(within(sets).getAllByRole('listitem').length).toBe(5));

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /^Отменить:/ }));
    });

    expect(undoQuickMark.mock.calls[0][0]).toBe(5);
    await waitFor(() => expect(screen.getByText('1000 мл')).toBeDefined());
    expect(screen.getByText('Итого за день: 1000 мл')).toBeDefined();
  });

  it('hands the keyboard back to the dialog while the list is up', async () => {
    listQuickMarks = mock(() => Promise.resolve([{ ...WATER_MARK, hotkey: 'w' }]));
    await renderToday();
    fireEvent.click(screen.getByRole('button', { name: OPEN_WATER_SETS }));
    await screen.findByRole('heading', { name: 'Питание — сегодня' });

    await act(async () => {
      fireEvent.keyDown(document, { key: 'w' });
    });

    expect(tapQuickMark).not.toHaveBeenCalled();
  });
});

describe('the day read again after a quick mark on /today', () => {
  it("reads today's records again after a tap, and nothing else of the screen", async () => {
    listQuickMarks = mock(() => Promise.resolve([WATER_MARK]));
    await renderToday();
    const entryReads = getEntries.mock.calls.length;
    const categoryReads = getCategories.mock.calls.length;
    const directoryReads = listQuickMarks.mock.calls.length;

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: WATER_MARK.label }));
    });

    expect(getEntries.mock.calls.length).toBe(entryReads + 1);
    expect(getCategories.mock.calls.length).toBe(categoryReads);
    expect(listQuickMarks.mock.calls.length).toBe(directoryReads);
  });

  it('reads them again after a tap made from the keyboard as well', async () => {
    listQuickMarks = mock(() => Promise.resolve([{ ...WATER_MARK, hotkey: 'w' }]));
    await renderToday();
    const entryReads = getEntries.mock.calls.length;

    await act(async () => {
      fireEvent.keyDown(document, { key: 'w' });
    });

    expect(tapQuickMark).toHaveBeenCalledTimes(1);
    expect(getEntries.mock.calls.length).toBe(entryReads + 1);
  });

  it('reads them again after the quick undo of the last tap', async () => {
    listQuickMarks = mock(() => Promise.resolve([WATER_MARK]));
    undoQuickMark = mock(() =>
      Promise.resolve({
        event_id: 1,
        quick_mark_id: WATER_MARK.id,
        entry_date: WATER_MARK.entry_date,
        undone_at: TIMESTAMP,
        today_total: 0,
        done: false,
      })
    );
    await renderToday();
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: WATER_MARK.label }));
    });
    const entryReads = getEntries.mock.calls.length;

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /^Отменить «/ }));
    });

    expect(undoQuickMark).toHaveBeenCalledTimes(1);
    expect(getEntries.mock.calls.length).toBe(entryReads + 1);
  });
});
