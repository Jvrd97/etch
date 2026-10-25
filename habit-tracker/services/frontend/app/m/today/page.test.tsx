// [review:need-review] PHASE-01/84-voice-day-input, PHASE-03/118, PHASE-03/121, PHASE-01/177, PHASE-01/206
// summary: tests for the two entry points on the mobile Today screen — dictation (the button opens the sheet, cancelling leaves the day untouched, a written day closes the sheet and reloads what Today shows) and the chat, whose conversation is started on the very date this screen is displaying
// summary: tests for the mobile Today screen — the dictation entry point (sheet opens, cancel leaves the day alone, a written day reloads it) and the quick-mark section, which is drawn from the directory and absent entirely when the directory is empty
// summary: the sets behind a quick-mark card on the mobile Today screen — the card's name and counter open a full-screen list of every set, the plus beside them still adds one and opens nothing, every tap reads the day's records and the streak of its category again, and a set taken back from the list lowers the card's counter

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import type { Category, Entry, QuickMark, QuickMarkDayEvent } from '@/lib/api';
import { TELL_DAY_LABEL } from '@/lib/ui-constants';

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

const MEAL = 'съел борщ и котлету';

/** Id of the conversation the chat entry point starts. */
const CONVERSATION_ID = 31;

const MEAL_PLAN = {
  metrics: [
    {
      op: 'log_metric' as const,
      category_id: 5,
      field_id: 9,
      value: 780,
      source_text: MEAL,
      uncertain: false,
      implausible: false,
      estimated: true,
    },
  ],
  checklist: [],
  unresolved: [],
  journal: null,
};

let getCategories: ReturnType<typeof mock>;
let getEntries: ReturnType<typeof mock>;
let listQuickMarks: ReturnType<typeof mock>;
let tapQuickMark: ReturnType<typeof mock>;
let undoQuickMark: ReturnType<typeof mock>;
let dayEvents: ReturnType<typeof mock>;
let getStreak: ReturnType<typeof mock>;

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
let draft: ReturnType<typeof mock>;
let applyPlan: ReturnType<typeof mock>;
let createConversation: ReturnType<typeof mock>;
let pushed: string[];

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
    tap: (id: number) => tapQuickMark(id),
    undo: (eventId: number) => undoQuickMark(eventId),
    dayEvents: (categoryId: number) => dayEvents(categoryId),
    sources: () => Promise.resolve([]),
  },
  // The chat client (#118). Present in every api mock for the same reason the
  // rest of the surface is: bun fixes a module's export names on first link, so
  // a mock that omits it deletes it for whoever runs next.
  chatAPI: {
    list: () => Promise.resolve([]),
    create: (options?: unknown) => createConversation(options),
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
    draft: (transcript: string, entryDate: string) => draft(transcript, entryDate),
    apply: (...args: unknown[]) => applyPlan(...args),
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
    getStreak: (id: number) => getStreak(id),
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
  // The Today screen now carries the challenge block (#127). Listed here for
  // the same reason as the rest: bun fixes a module's export names on first
  // link, and an omitted one is deleted for whoever imports it next.
  challengesAPI: {
    list: () => Promise.resolve([]),
    get: () => Promise.resolve(null),
    create: () => Promise.resolve(null),
    patch: () => Promise.resolve(null),
    recompute: () => Promise.resolve(null),
  },
  tableAPI: { get: () => Promise.resolve({ days: [] }) },
  journalAPI: { getAll: () => Promise.resolve({ total: 0, items: [] }) },
}));

mock.module('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
  usePathname: () => '/m/today',
  useRouter: () => ({
    push: (href: string) => {
      pushed.push(href);
    },
    replace: () => {},
  }),
}));

const { default: MobileTodayPage } = await import('./page');
const { ASK_ABOUT_DAY_LABEL } = await import('@/components/chat/AskAboutDayButton');
const { START_DICTATION_LABEL, VOICE_SHEET_TITLE } = await import(
  '@/components/mobile/VoiceDaySheet'
);

/** The half of the Web Speech API the sheet drives, driveable from a test. */
class FakeRecognition {
  static instances: FakeRecognition[] = [];

  lang = '';
  continuous = false;
  interimResults = false;

  onresult:
    | ((event: {
        resultIndex: number;
        results: ArrayLike<{
          isFinal: boolean;
          0: { transcript: string };
          length: number;
        }>;
      }) => void)
    | null = null;
  onerror: ((event: { error: string }) => void) | null = null;
  onend: (() => void) | null = null;

  constructor() {
    FakeRecognition.instances.push(this);
  }

  start(): void {}
  stop(): void {
    this.onend?.();
  }
  abort(): void {}

  say(transcript: string): void {
    this.onresult?.({
      resultIndex: 0,
      results: [{ isFinal: true, 0: { transcript }, length: 1 }],
    });
  }
}

type SpeechWindow = typeof globalThis & { SpeechRecognition?: unknown };

/**
 * Open the dictation sheet and let its own catalogue request settle.
 *
 * The sheet resolves the plan's ids to names through `categoriesAPI`, fetched
 * on mount. Without flushing it, the synchronous assertions below land first
 * and React reports the resulting state update as happening outside `act`.
 */
async function openSheet() {
  fireEvent.click(screen.getByRole('button', { name: TELL_DAY_LABEL }));
  await act(async () => {});
}

/** Render Today and let its catalogue and entries requests settle. */
async function renderToday() {
  render(<MobileTodayPage />);
  await waitFor(() => expect(screen.getByRole('button', { name: TELL_DAY_LABEL })).toBeDefined());
}

beforeEach(() => {
  FakeRecognition.instances = [];
  (globalThis as SpeechWindow).SpeechRecognition = FakeRecognition;
  getCategories = mock(() => Promise.resolve([NUTRITION]));
  getEntries = mock(() => Promise.resolve([] as Entry[]));
  draft = mock(() => Promise.resolve(MEAL_PLAN));
  applyPlan = mock(() => Promise.resolve({ entry_ids: [1] }));
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
  getStreak = mock(() => Promise.resolve(null));
  createConversation = mock(() => Promise.resolve({ id: CONVERSATION_ID }));
  pushed = [];
});

afterEach(() => {
  cleanup();
  delete (globalThis as SpeechWindow).SpeechRecognition;
});

describe('dictating a day from /m/today', () => {
  it('offers the day out loud without leaving the screen', async () => {
    // The whole point of the entry point: the parse screen exists already, and
    // navigating to it is the step that stopped it from being used.
    await renderToday();

    await openSheet();

    expect(screen.getByRole('dialog', { name: VOICE_SHEET_TITLE })).toBeDefined();
  });

  it('leaves the day alone when the sheet is dismissed', async () => {
    await renderToday();
    await openSheet();

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(screen.queryByRole('dialog', { name: VOICE_SHEET_TITLE })).toBeNull();
    expect(applyPlan).not.toHaveBeenCalled();
  });

  it('closes the sheet and refreshes Today once the day is written', async () => {
    // A dictated meal changes exactly what this screen is showing. Leaving the
    // old numbers up is how a user ends up logging the same lunch twice.
    await renderToday();
    const loadsBefore = getEntries.mock.calls.length;
    await openSheet();
    fireEvent.click(screen.getByRole('button', { name: START_DICTATION_LABEL }));
    act(() => FakeRecognition.instances[0].say(MEAL));
    fireEvent.click(screen.getByRole('button', { name: /Разобрать день/ }));
    await waitFor(() => expect(screen.getByLabelText(`Записать ${MEAL}`)).toBeDefined());

    fireEvent.click(screen.getByRole('button', { name: /Записать \(/ }));
    // The write and the reload it triggers are two chained promises; flushing
    // them inside `act` keeps the assertions below reading a settled screen.
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.queryByRole('dialog', { name: VOICE_SHEET_TITLE })).toBeNull();
    expect(getEntries.mock.calls.length).toBeGreaterThan(loadsBefore);
  });
});


describe('the quick marks of /m/today', () => {
  it('opens without a quick-mark section when the directory is empty', async () => {
    // The directory starts empty and is filled by hand: an empty one has to be
    // an ordinary screen, not an error and not an instruction.
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

  it('drops the legacy quick-input card of a category the directory covers', async () => {
    // Two ways to add to the same field on one screen is one too many; the card
    // of a category with no button stays exactly where it was.
    listQuickMarks = mock(() => Promise.resolve([WATER_MARK]));
    await renderToday();

    expect(screen.queryByLabelText('Питание: add Калории')).toBeNull();
  });

  it('keeps the card of a category the directory does not cover', async () => {
    await renderToday();

    expect(screen.getByLabelText('Питание: add Калории')).toBeDefined();
  });

  it('opens the confirmed entries of a category in a full-screen sheet', async () => {
    getEntries = mock(() => Promise.resolve([
      {
        id: 12, category_id: NUTRITION.id, entry_date: '2026-07-30',
        created_at: '2026-07-30T09:12:00Z', updated_at: TIMESTAMP,
        values: [{ id: 13, entry_id: 12, field_id: 9, value: '300' }],
      },
    ]));
    await renderToday();

    fireEvent.click(screen.getByRole('button', { name: "Open today's Питание entry" }));
    expect(screen.getByRole('dialog', { name: 'Питание — сегодня' })).toBeDefined();
    expect(screen.getByText('Калории 300')).toBeDefined();
  });
});

describe('asking about the day from /m/today', () => {
  it('starts the conversation on the date the screen is showing', async () => {
    // Экран знает свой день и обязан передать именно его: разговор, заведённый
    // «на сегодня по мнению сервера», окажется про другой день, как только
    // Today покажет не сегодняшнюю дату.
    await renderToday();
    const shownDate = screen.getByText(/^\d{4}-\d{2}-\d{2}$/).textContent;

    fireEvent.click(screen.getByRole('button', { name: ASK_ABOUT_DAY_LABEL }));

    await waitFor(() => expect(createConversation).toHaveBeenCalledTimes(1));
    expect(createConversation.mock.calls[0][0]).toEqual({
      started_on: shownDate,
      kind: 'general',
    });
  });

  it('opens that conversation in the mobile shell, not the desktop one', async () => {
    await renderToday();

    fireEvent.click(screen.getByRole('button', { name: ASK_ABOUT_DAY_LABEL }));

    await waitFor(() => expect(pushed).toEqual([`/m/chat?conversation=${CONVERSATION_ID}`]));
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

/** Five taps of the water button, the way the journal would hold them. */
function fiveSets(): QuickMarkDayEvent[] {
  return [1, 2, 3, 4, 5].map((n) =>
    waterSet(n, `2026-07-30T0${n}:00:00Z`, n === 5)
  );
}

describe('the sets behind a quick-mark card on /m/today', () => {
  it('opens a full-screen list of every set from the name and counter of the card', async () => {
    listQuickMarks = mock(() => Promise.resolve([{ ...WATER_MARK, today_total: 1250, done: true }]));
    dayEvents = mock(() => Promise.resolve(fiveSets()));
    await renderToday();

    fireEvent.click(screen.getByRole('button', { name: OPEN_WATER_SETS }));

    const sheet = await screen.findByRole('dialog', { name: 'Питание — сегодня' });
    await waitFor(() => expect(within(sheet).getAllByRole('listitem').length).toBe(5));
    expect(dayEvents.mock.calls[0][0]).toBe(NUTRITION.id);
    expect(within(sheet).getByText('Итого за день: 1250 мл')).toBeDefined();
  });

  it('keeps the plus adding a set without opening anything', async () => {
    listQuickMarks = mock(() => Promise.resolve([WATER_MARK]));
    await renderToday();

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: WATER_MARK.label }));
    });

    expect(tapQuickMark).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(dayEvents).not.toHaveBeenCalled();
  });

  it('puts the confirmed records of the category under the sets', async () => {
    listQuickMarks = mock(() => Promise.resolve([WATER_MARK]));
    getEntries = mock(() =>
      Promise.resolve([
        {
          id: 12, category_id: NUTRITION.id, entry_date: '2026-07-30',
          created_at: '2026-07-30T09:12:00Z', updated_at: TIMESTAMP,
          values: [{ id: 13, entry_id: 12, field_id: 9, value: '1250' }],
        },
      ])
    );
    await renderToday();

    fireEvent.click(screen.getByRole('button', { name: OPEN_WATER_SETS }));

    const sheet = await screen.findByRole('dialog', { name: 'Питание — сегодня' });
    expect(within(sheet).getByText('Записи за день')).toBeDefined();
    expect(within(sheet).getByText('Калории 1250')).toBeDefined();
  });

  it('shows the list without a category card when the category is not an active one', async () => {
    getCategories = mock(() => Promise.resolve([] as Category[]));
    listQuickMarks = mock(() => Promise.resolve([WATER_MARK]));
    await renderToday();

    fireEvent.click(screen.getByRole('button', { name: OPEN_WATER_SETS }));

    const sheet = await screen.findByRole('dialog', { name: '+250 мл — сегодня' });
    expect(within(sheet).queryByRole('button', { name: 'Add entry' })).toBeNull();
    expect(within(sheet).getByRole('button', { name: 'Добавить' }).hasAttribute('disabled')).toBe(true);
  });

  it('closes the list with Cancel and leaves the card where it was', async () => {
    listQuickMarks = mock(() => Promise.resolve([WATER_MARK]));
    await renderToday();
    fireEvent.click(screen.getByRole('button', { name: OPEN_WATER_SETS }));
    await screen.findByRole('dialog', { name: 'Питание — сегодня' });

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getByRole('button', { name: OPEN_WATER_SETS })).toBeDefined();
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
    expect(screen.getByText('1250 мл')).toBeDefined();
    fireEvent.click(screen.getByRole('button', { name: OPEN_WATER_SETS }));
    const sheet = await screen.findByRole('dialog', { name: 'Питание — сегодня' });
    await waitFor(() => expect(within(sheet).getAllByRole('listitem').length).toBe(5));

    await act(async () => {
      fireEvent.click(within(sheet).getByRole('button', { name: /^Отменить:/ }));
    });

    expect(undoQuickMark.mock.calls[0][0]).toBe(5);
    await waitFor(() => expect(screen.getByText('1000 мл')).toBeDefined());
    expect(within(sheet).getByText('Итого за день: 1000 мл')).toBeDefined();
    // The list was read again, so the row that is no longer last is not offered.
    await waitFor(() => expect(dayEvents).toHaveBeenCalledTimes(2));
  });
});

describe('the day read again after a quick mark on /m/today', () => {
  it("reads today's records again after every tap, and nothing else of the screen", async () => {
    listQuickMarks = mock(() => Promise.resolve([WATER_MARK]));
    await renderToday();
    const entryReads = getEntries.mock.calls.length;
    const categoryReads = getCategories.mock.calls.length;
    const directoryReads = listQuickMarks.mock.calls.length;

    for (let tap = 0; tap < 3; tap += 1) {
      // The first answer marks the card done, and the done card says so in its
      // name — the pattern keeps finding the plus across that change.
      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: /^\+250 мл/ }));
      });
    }

    expect(getEntries.mock.calls.length).toBe(entryReads + 3);
    expect(getCategories.mock.calls.length).toBe(categoryReads);
    expect(listQuickMarks.mock.calls.length).toBe(directoryReads);
  });

  it("shows the record the tap wrote, without a reload of the page", async () => {
    listQuickMarks = mock(() => Promise.resolve([WATER_MARK]));
    await renderToday();
    getEntries = mock(() =>
      Promise.resolve([
        {
          id: 12, category_id: NUTRITION.id, entry_date: '2026-07-30',
          created_at: '2026-07-30T09:12:00Z', updated_at: TIMESTAMP,
          values: [{ id: 13, entry_id: 12, field_id: 9, value: '250' }],
        },
      ])
    );
    fireEvent.click(screen.getByRole('button', { name: OPEN_WATER_SETS }));
    const sheet = await screen.findByRole('dialog', { name: 'Питание — сегодня' });
    expect(within(sheet).queryByText('Калории 250')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: WATER_MARK.label }));
    });
    fireEvent.click(screen.getByRole('button', { name: OPEN_WATER_SETS }));

    const reopened = await screen.findByRole('dialog', { name: 'Питание — сегодня' });
    expect(within(reopened).getByText('Калории 250')).toBeDefined();
  });

  it('reads the streak of an avoid category again after a relapse tap', async () => {
    const SMOKING: Category = {
      ...NUTRITION,
      id: 8,
      name: 'Курение',
      streak_mode: 'avoid',
      fields: [{ ...NUTRITION.fields[0], id: 21, category_id: 8, name: 'Штук' }],
    };
    const CIGARETTE: QuickMark = {
      ...WATER_MARK,
      id: 9,
      label: 'Сигарета',
      category_id: SMOKING.id,
      field_id: 21,
      kind: 'relapse',
      step: 1,
      unit_label: null,
    };
    getCategories = mock(() => Promise.resolve([SMOKING]));
    listQuickMarks = mock(() => Promise.resolve([CIGARETTE]));
    tapQuickMark = mock(() =>
      Promise.resolve({
        event_id: 7,
        quick_mark_id: CIGARETTE.id,
        entry_id: 50,
        entry_date: CIGARETTE.entry_date,
        occurred_at: TIMESTAMP,
        today_total: 1,
        done: true,
      })
    );
    await renderToday();
    getStreak.mockClear();

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: CIGARETTE.label }));
    });

    expect(getStreak).toHaveBeenCalledTimes(1);
    expect(getStreak.mock.calls[0][0]).toBe(SMOKING.id);
  });

  it('leaves the streaks alone after a tap on a category that has none', async () => {
    listQuickMarks = mock(() => Promise.resolve([WATER_MARK]));
    await renderToday();
    getStreak.mockClear();

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: WATER_MARK.label }));
    });

    expect(getStreak).not.toHaveBeenCalled();
  });
});
