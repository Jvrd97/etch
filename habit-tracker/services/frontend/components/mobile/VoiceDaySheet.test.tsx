// [review:need-review] PHASE-01/84-voice-day-input
// summary: tests for the dictation sheet — speech lands in an editable field, the one bar action carries both steps (parse, then write), an estimated meal is labelled as an estimate, a browser that cannot listen still lets the day be typed, and closing the sheet stops the microphone

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type {
  Category,
  CheckOp,
  DailySummaryPlan,
  JournalOp,
  LogMetricOp,
} from '@/lib/api';

const TIMESTAMP = '2026-07-30T00:00:00Z';

/** The catalogue the plan's ids resolve against: names are what the card shows. */
const NUTRITION: Category = {
  id: 5,
  name: 'Питание',
  display_mode: 'form',
  streak_mode: 'build',
  is_active: true,
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

/** What a described meal comes back as: a number nobody said, marked as such. */
const MEAL_PLAN: DailySummaryPlan = {
  metrics: [
    {
      op: 'log_metric',
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

let draft: ReturnType<typeof mock>;
let applyPlan: ReturnType<typeof mock>;
let getCategories: ReturnType<typeof mock>;

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
    list: () => Promise.resolve([]),
    tap: () => Promise.resolve(null),
    undo: () => Promise.resolve(null),
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
  // The day screen's client (#86). Present in every api mock for the same
  // reason the rest of the surface is: bun fixes a module's export names on
  // first link, so a mock that omits it deletes it for whoever runs next.
  dayAPI: {
    getToday: () => Promise.resolve(null),
    get: () => Promise.resolve(null),
  },
  dailySummaryAPI: {
    draft: (transcript: string, entryDate: string) => draft(transcript, entryDate),
    apply: (
      entryDate: string,
      metrics: LogMetricOp[],
      checklist: CheckOp[],
      journal: JournalOp | null,
      idempotencyKey: string
    ) => applyPlan(entryDate, metrics, checklist, journal, idempotencyKey),
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
    getAll: () => Promise.resolve([]),
    create: () => Promise.resolve(null),
    update: () => Promise.resolve(null),
    delete: () => Promise.resolve(undefined),
    upsertChecklist: () => Promise.resolve({}),
  },
  tableAPI: { get: () => Promise.resolve({ days: [] }) },
  journalAPI: { getAll: () => Promise.resolve({ total: 0, items: [] }) },
}));

const { default: VoiceDaySheet, DICTATION_FIELD_LABEL, PARSE_LABEL, VOICE_SHEET_TITLE } =
  await import('./VoiceDaySheet');
const { ESTIMATED_NOTE } = await import('@/hooks/useDailySummary');
const { START_DICTATION_LABEL, STOP_DICTATION_LABEL, UNSUPPORTED_HINT } = await import(
  './VoiceDaySheet'
);

/** The half of the Web Speech API the sheet drives, driveable from a test. */
class FakeRecognition {
  static instances: FakeRecognition[] = [];

  lang = '';
  continuous = false;
  interimResults = false;
  aborted = 0;
  stopped = 0;

  onresult:
    | ((event: {
        resultIndex: number;
        results: ArrayLike<{ isFinal: boolean; 0: { transcript: string }; length: number }>;
      }) => void)
    | null = null;
  onerror: ((event: { error: string }) => void) | null = null;
  onend: (() => void) | null = null;

  constructor() {
    FakeRecognition.instances.push(this);
  }

  start(): void {}

  stop(): void {
    this.stopped += 1;
    this.onend?.();
  }

  abort(): void {
    this.aborted += 1;
  }

  say(transcript: string): void {
    this.onresult?.({
      resultIndex: 0,
      results: [{ isFinal: true, 0: { transcript }, length: 1 }],
    });
  }
}

type SpeechWindow = typeof globalThis & { SpeechRecognition?: unknown };

function withMicrophone(): void {
  FakeRecognition.instances = [];
  (globalThis as SpeechWindow).SpeechRecognition = FakeRecognition;
}

function microphone(): FakeRecognition {
  const instance = FakeRecognition.instances.at(-1);
  if (!instance) throw new Error('the sheet never opened a recogniser');
  return instance;
}

function field(): HTMLTextAreaElement {
  return screen.getByLabelText(DICTATION_FIELD_LABEL) as HTMLTextAreaElement;
}

function barAction(): HTMLButtonElement {
  return screen.getByRole('button', { name: new RegExp(PARSE_LABEL) }) as HTMLButtonElement;
}

/**
 * Render the sheet and let the catalogue request settle.
 *
 * The preview resolves ids to names through `categoriesAPI`, which the hook
 * fetches on mount. Without flushing it here, every synchronous assertion below
 * would land before that promise and React would report the state update it
 * causes as happening outside `act`.
 */
async function renderSheet(onApplied = mock(() => {}), onClose = mock(() => {})) {
  const utils = render(<VoiceDaySheet onClose={onClose} onApplied={onApplied} />);
  await act(async () => {});
  return utils;
}

/** Open the sheet, dictate a meal and parse it into a plan. */
async function renderWithDictatedPlan(onApplied = mock(() => {})) {
  await renderSheet(onApplied);
  fireEvent.click(screen.getByRole('button', { name: START_DICTATION_LABEL }));
  act(() => microphone().say(MEAL));
  fireEvent.click(barAction());
  await waitFor(() => expect(screen.getByLabelText(`Записать ${MEAL}`)).toBeDefined());
}

beforeEach(() => {
  withMicrophone();
  draft = mock(() => Promise.resolve(MEAL_PLAN));
  applyPlan = mock(() => Promise.resolve({ entry_ids: [1] }));
  getCategories = mock(() => Promise.resolve([NUTRITION]));
});

afterEach(() => {
  cleanup();
  delete (globalThis as SpeechWindow).SpeechRecognition;
});

describe('dictating a day', () => {
  it('opens on the recording step, named for what it does', async () => {
    await renderSheet();

    expect(screen.getByRole('dialog', { name: VOICE_SHEET_TITLE })).toBeDefined();
    expect(screen.getByRole('button', { name: START_DICTATION_LABEL })).toBeDefined();
  });

  it('writes what was heard into a field the user can still fix', async () => {
    // Speech recognition mishears, and a day that can only be re-dictated is a
    // day the user gives up on. The text stays editable at every step.
    await renderSheet();
    fireEvent.click(screen.getByRole('button', { name: START_DICTATION_LABEL }));

    act(() => microphone().say(MEAL));

    expect(field().value).toBe(MEAL);
    fireEvent.change(field(), { target: { value: 'съел борщ и две котлеты' } });
    expect(field().value).toBe('съел борщ и две котлеты');
  });

  it('keeps sentences apart as they arrive', async () => {
    await renderSheet();
    fireEvent.click(screen.getByRole('button', { name: START_DICTATION_LABEL }));

    act(() => microphone().say('отжался 30 раз'));
    act(() => microphone().say(MEAL));

    // Without the separator the two phrases fuse into "разсъел", which the
    // model then has to unpick — and it is the user's own text that suffers.
    expect(field().value).toBe(`отжался 30 раз ${MEAL}`);
  });

  it('turns the microphone off on a second press', async () => {
    await renderSheet();
    fireEvent.click(screen.getByRole('button', { name: START_DICTATION_LABEL }));

    fireEvent.click(screen.getByRole('button', { name: STOP_DICTATION_LABEL }));

    expect(microphone().stopped).toBe(1);
    expect(screen.getByRole('button', { name: START_DICTATION_LABEL })).toBeDefined();
  });

  it('closes the microphone when the sheet goes away', async () => {
    // Left open, it is a recording indicator in the status bar that the user
    // has no way to connect back to a sheet they already dismissed.
    const { unmount } = await renderSheet();
    fireEvent.click(screen.getByRole('button', { name: START_DICTATION_LABEL }));

    unmount();

    expect(microphone().aborted).toBe(1);
  });

  it('still takes a typed day where nothing can listen', async () => {
    delete (globalThis as SpeechWindow).SpeechRecognition;
    await renderSheet();

    expect(screen.queryByRole('button', { name: START_DICTATION_LABEL })).toBeNull();
    expect(screen.getByText(UNSUPPORTED_HINT)).toBeDefined();
    fireEvent.change(field(), { target: { value: MEAL } });
    expect(barAction().disabled).toBe(false);
  });

  it('has nothing to parse until something has been said', async () => {
    await renderSheet();

    expect(barAction().disabled).toBe(true);
  });
});

describe('reviewing and writing a dictated day', () => {
  it('sends the dictated text to be parsed', async () => {
    await renderWithDictatedPlan();

    expect(draft).toHaveBeenCalledTimes(1);
    expect((draft.mock.calls[0] as unknown[])[0]).toBe(MEAL);
  });

  it('says which numbers it estimated rather than heard', async () => {
    // The whole point of speaking a meal is that the numbers come from the
    // model. Shipping them unlabelled would put four invented numbers in a
    // diary under the user's own name.
    await renderWithDictatedPlan();

    expect(screen.getByText(ESTIMATED_NOTE)).toBeDefined();
    expect(screen.getByText(/780 · Питание · Калории/)).toBeDefined();
  });

  it('brings an estimate in checked, unlike a doubtful metric', async () => {
    // An estimate is a guess about the portion, not about where it goes: the
    // user's own words already chose the category. Making them tick four boxes
    // per meal is the friction this whole feature exists to remove.
    await renderWithDictatedPlan();

    expect((screen.getByLabelText(`Записать ${MEAL}`) as HTMLInputElement).checked).toBe(
      true
    );
  });

  it('writes the day and hands back to the screen underneath', async () => {
    const onApplied = mock(() => {});
    await renderWithDictatedPlan(onApplied);

    fireEvent.click(screen.getByRole('button', { name: /Записать/ }));

    await waitFor(() => expect(applyPlan).toHaveBeenCalledTimes(1));
    const [, metrics] = applyPlan.mock.calls[0] as [string, LogMetricOp[]];
    expect(metrics).toHaveLength(1);
    expect(metrics[0].value).toBe(780);
    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1));
  });

  it('writes nothing once the only row is unchecked', async () => {
    await renderWithDictatedPlan();

    fireEvent.click(screen.getByLabelText(`Записать ${MEAL}`));

    expect(
      (screen.getByRole('button', { name: /Записать/ }) as HTMLButtonElement).disabled
    ).toBe(true);
  });

  it('keeps the spoken text when the model cannot be reached', async () => {
    // Re-dictating a day because the backend blinked is the one thing this
    // sheet must never ask for.
    draft = mock(() => Promise.reject(new Error('LLM недоступен')));
    await renderSheet();
    fireEvent.click(screen.getByRole('button', { name: START_DICTATION_LABEL }));
    act(() => microphone().say(MEAL));

    fireEvent.click(barAction());

    await waitFor(() => expect(screen.getByText(/LLM недоступен/)).toBeDefined());
    expect(field().value).toBe(MEAL);
  });
});
