// [review:need-review] PHASE-01/84-voice-day-input
// summary: tests for the dictation entry point on the mobile Today screen — the button opens the sheet, cancelling leaves the day untouched, and a written day closes the sheet and reloads what Today shows

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { Category, Entry } from '@/lib/api';

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
