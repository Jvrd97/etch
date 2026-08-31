// [review:need-review] PHASE-01/84-voice-day-input, PHASE-03/121
// summary: tests for the mobile Today screen — the dictation entry point (sheet opens, cancel leaves the day alone, a written day reloads it) and the quick-mark section, which is drawn from the directory and absent entirely when the directory is empty

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { Category, Entry, QuickMark } from '@/lib/api';

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
};
let draft: ReturnType<typeof mock>;
let applyPlan: ReturnType<typeof mock>;

// Declares the whole @/lib/api surface: bun fixes a module's export names the
// first time anything links against it and shares that registry across the run.
mock.module('@/lib/api', () => ({
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
  usePathname: () => '/m/today',
  useRouter: () => ({ push: () => {}, replace: () => {} }),
}));

const { default: MobileTodayPage } = await import('./page');
const { TELL_DAY_LABEL } = await import('./page');
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
    })
  );
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
});
