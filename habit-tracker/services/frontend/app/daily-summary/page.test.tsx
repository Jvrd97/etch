// [review:need-review] PHASE-01/75-daily-summary-checklist
// summary: desktop day-summary tests — text -> plan -> unchecked rows -> apply -> redirect, the checklist section (ticks only, checklist named per row), the journal op (append checked, replace offered and off), the unresolved section, and the LLM error with Retry

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import type {
  Category,
  CheckOp,
  DailySummaryPlan,
  JournalOp,
  LogMetricOp,
} from '@/lib/api';
import { CHECKLIST_TITLE } from '@/hooks/useDailySummary';

const TIMESTAMP = '2026-07-30T00:00:00Z';

/** The catalogue the plan's ids resolve against: names are what the row shows. */
const SPORT: Category = {
  id: 1,
  name: 'Спорт',
  display_mode: 'form',
  streak_mode: 'build',
  is_active: true,
  created_at: TIMESTAMP,
  updated_at: TIMESTAMP,
  fields: [
    {
      id: 2,
      category_id: 1,
      name: 'Отжимания',
      field_type: 'number',
      is_required: false,
      order: 0,
      created_at: TIMESTAMP,
      updated_at: TIMESTAMP,
    },
    {
      id: 3,
      category_id: 1,
      name: 'Подтягивания',
      field_type: 'number',
      is_required: false,
      order: 1,
      created_at: TIMESTAMP,
      updated_at: TIMESTAMP,
    },
  ],
};

const PLAN: DailySummaryPlan = {
  metrics: [
    {
      op: 'log_metric',
      category_id: 1,
      field_id: 2,
      value: 30,
      source_text: 'отжался 30 раз',
      uncertain: false,
      implausible: false,
    },
    {
      op: 'log_metric',
      category_id: 1,
      field_id: 3,
      value: 300,
      source_text: 'подтянулся 300 раз',
      uncertain: false,
      implausible: true,
    },
  ],
  unresolved: [{ text: 'погулял с собакой', reason: 'нет категории' }],
  journal: null,
};

const VITAMINS: Category = {
  id: 4,
  name: 'Витамины',
  display_mode: 'checklist',
  streak_mode: 'build',
  is_active: true,
  created_at: TIMESTAMP,
  updated_at: TIMESTAMP,
  fields: [
    {
      id: 9,
      category_id: 4,
      name: 'B12',
      field_type: 'boolean',
      is_required: false,
      order: 0,
      created_at: TIMESTAMP,
      updated_at: TIMESTAMP,
    },
  ],
};

const CHECK: CheckOp = {
  op: 'check',
  category_id: 4,
  field_id: 9,
  source_text: 'выпил B12',
  uncertain: false,
};

const JOURNAL: JournalOp = {
  op: 'write_journal',
  title: 'Разбор дня',
  content: '## Спорт\n\nОтжался 30 раз.',
  mood: null,
  tags: null,
  mode: 'append',
  existing_entry_id: 7,
};

let draft: ReturnType<typeof mock>;
let applyPlan: ReturnType<typeof mock>;
let pushRoute: ReturnType<typeof mock>;
let getCategories: ReturnType<typeof mock>;

// Declares the whole @/lib/api surface: bun fixes a module's export names the
// first time anything links against it and shares that registry across the run,
// so a partial mock would delete members other suites reach for.
mock.module('@/lib/api', () => ({
  // The chat client (#118). Present in every api mock for the same reason the
  // rest of the surface is: bun fixes a module's export names on first link, so
  // a mock that omits it deletes it for whoever runs next.
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

mock.module('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
  usePathname: () => '/daily-summary',
  useRouter: () => ({ push: (href: string) => pushRoute(href), replace: () => {} }),
}));

const { default: DailySummaryPage } = await import('./page');

/** Render, generate a plan, and wait for the preview to settle. */
async function renderWithPlan() {
  render(<DailySummaryPage />);
  fireEvent.change(screen.getByLabelText('Как прошёл день'), {
    target: { value: 'отжался 30 раз, подтянулся 300 раз, погулял с собакой' },
  });
  fireEvent.click(screen.getByRole('button', { name: /Разобрать день/ }));
  await waitFor(() => expect(screen.getByLabelText('Записать отжался 30 раз')).toBeDefined());
}

beforeEach(() => {
  draft = mock(() => Promise.resolve(PLAN));
  applyPlan = mock(() => Promise.resolve({ entry_ids: [1] }));
  pushRoute = mock(() => {});
  getCategories = mock(() => Promise.resolve([SPORT]));
});

afterEach(() => {
  cleanup();
});

describe('/daily-summary', () => {
  it('checks a confident metric and leaves an implausible one alone', async () => {
    await renderWithPlan();

    expect(
      (screen.getByLabelText('Записать отжался 30 раз') as HTMLInputElement).checked
    ).toBe(true);
    expect(
      (screen.getByLabelText('Записать подтянулся 300 раз') as HTMLInputElement).checked
    ).toBe(false);
  });

  it('names the category and the field each metric would go into', async () => {
    await renderWithPlan();

    await waitFor(() =>
      expect(screen.getByText(/Спорт · Отжимания/)).toBeDefined()
    );
    expect(screen.getByText(/Спорт · Подтягивания/)).toBeDefined();
    expect(screen.queryByText(/категория #1/)).toBeNull();
  });

  it('falls back to ids when the catalogue has no such category', async () => {
    getCategories = mock(() => Promise.resolve([]));
    await renderWithPlan();

    await waitFor(() =>
      expect(screen.getAllByText(/категория #1 · поле #/)).toHaveLength(2)
    );
  });

  it('shows what the model could not place, without a checkbox', async () => {
    await renderWithPlan();

    const section = screen.getByLabelText('Не нашлось категории');
    expect(within(section).getByText(/погулял с собакой/)).toBeDefined();
    expect(screen.queryByLabelText('Записать погулял с собакой')).toBeNull();
  });

  it('writes only the checked metrics, then lands on Entries', async () => {
    await renderWithPlan();

    fireEvent.click(screen.getByLabelText('Записать отжался 30 раз'));
    fireEvent.click(screen.getByLabelText('Записать подтянулся 300 раз'));
    fireEvent.click(screen.getByRole('button', { name: /Записать выбранное/ }));

    await waitFor(() => expect(applyPlan).toHaveBeenCalledTimes(1));
    const metrics = applyPlan.mock.calls[0][1] as LogMetricOp[];
    expect(metrics).toHaveLength(1);
    expect(metrics[0].field_id).toBe(3);
    await waitFor(() => expect(pushRoute).toHaveBeenCalledWith('/entries'));
  });

  it('offers to append the day text, with replacement present and off', async () => {
    draft = mock(() => Promise.resolve({ ...PLAN, journal: JOURNAL }));
    await renderWithPlan();

    const append = screen.getByLabelText('Дополнить запись дня') as HTMLInputElement;
    const replace = screen.getByLabelText('Заменить текст') as HTMLInputElement;
    expect(append.checked).toBe(true);
    expect(replace.checked).toBe(false);
    expect(replace.disabled).toBe(false);
  });

  it('sends the day text with the metrics, as an append by default', async () => {
    draft = mock(() => Promise.resolve({ ...PLAN, journal: JOURNAL }));
    await renderWithPlan();

    fireEvent.click(screen.getByRole('button', { name: /Записать выбранное/ }));

    await waitFor(() => expect(applyPlan).toHaveBeenCalledTimes(1));
    const journal = applyPlan.mock.calls[0][3] as JournalOp;
    expect(journal.mode).toBe('append');
    expect(journal.content).toBe(JOURNAL.content);
  });

  it('replaces the day text only after the user checks it', async () => {
    draft = mock(() => Promise.resolve({ ...PLAN, journal: JOURNAL }));
    await renderWithPlan();

    fireEvent.click(screen.getByLabelText('Заменить текст'));
    fireEvent.click(screen.getByRole('button', { name: /Записать выбранное/ }));

    await waitFor(() => expect(applyPlan).toHaveBeenCalledTimes(1));
    expect((applyPlan.mock.calls[0][3] as JournalOp).mode).toBe('replace');
  });

  it('keeps the write available when only the day text is checked', async () => {
    draft = mock(() =>
      Promise.resolve({ metrics: [], unresolved: [], journal: JOURNAL })
    );
    render(<DailySummaryPage />);
    fireEvent.change(screen.getByLabelText('Как прошёл день'), {
      target: { value: 'день был длинный' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Разобрать день/ }));
    await waitFor(() =>
      expect(screen.getByLabelText('Дополнить запись дня')).toBeDefined()
    );

    fireEvent.click(screen.getByRole('button', { name: /Записать выбранное/ }));

    await waitFor(() => expect(applyPlan).toHaveBeenCalledTimes(1));
    expect(applyPlan.mock.calls[0][1]).toEqual([]);
  });

  it('offers a retry and keeps the text when the model is unreachable', async () => {
    draft = mock(() => Promise.reject(new Error('LLM backend unavailable')));
    render(<DailySummaryPage />);
    const textarea = screen.getByLabelText('Как прошёл день') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'отжался 30 раз' } });
    fireEvent.click(screen.getByRole('button', { name: /Разобрать день/ }));

    await waitFor(() =>
      expect(screen.getByText('LLM backend unavailable')).toBeDefined()
    );
    expect(screen.getByRole('button', { name: /Retry/ })).toBeDefined();
    expect(textarea.value).toBe('отжался 30 раз');
  });

  it('keeps the plan on screen when the write is rejected', async () => {
    applyPlan = mock(() => Promise.reject(new Error('unknown category_id 1')));
    await renderWithPlan();

    fireEvent.click(screen.getByRole('button', { name: /Записать выбранное/ }));

    await waitFor(() => expect(screen.getByText('unknown category_id 1')).toBeDefined());
    expect(screen.getByLabelText('Записать отжался 30 раз')).toBeDefined();
    expect(pushRoute).not.toHaveBeenCalled();
  });
});

describe('/daily-summary checklist section', () => {
  /** Render and settle a plan whose only operation is one tick. */
  async function renderWithChecklist(check: CheckOp = CHECK) {
    draft = mock(() =>
      Promise.resolve({ metrics: [], unresolved: [], checklist: [check] })
    );
    getCategories = mock(() => Promise.resolve([SPORT, VITAMINS]));
    render(<DailySummaryPage />);
    fireEvent.change(screen.getByLabelText('Как прошёл день'), {
      target: { value: 'выпил B12' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Разобрать день/ }));
    await waitFor(() => expect(screen.getByLabelText(CHECKLIST_TITLE)).toBeDefined());
  }

  it('shows the ticks in their own section, checked, with their checklist named', async () => {
    await renderWithChecklist();

    const section = screen.getByLabelText(CHECKLIST_TITLE);
    expect(
      (within(section).getByLabelText('Отметить выпил B12') as HTMLInputElement).checked
    ).toBe(true);
    await waitFor(() =>
      expect(within(section).getByText(/Витамины · B12/)).toBeDefined()
    );
  });

  it('leaves an uncertain tick unchecked', async () => {
    await renderWithChecklist({ ...CHECK, uncertain: true });

    expect(
      (screen.getByLabelText('Отметить выпил B12') as HTMLInputElement).checked
    ).toBe(false);
  });

  it('writes a day that is nothing but a tick, then lands on Entries', async () => {
    await renderWithChecklist();

    fireEvent.click(screen.getByRole('button', { name: /Записать выбранное \(1\)/ }));

    await waitFor(() => expect(pushRoute).toHaveBeenCalledWith('/entries'));
    const checklist = applyPlan.mock.calls[0][2] as CheckOp[];
    expect(checklist).toHaveLength(1);
    expect(checklist[0].field_id).toBe(9);
  });

  it('sends an empty checklist once the tick is unchecked', async () => {
    // The journal keeps the write available, so the apply actually runs and
    // the payload can be read: a plan whose only op is unchecked has nothing
    // to write at all, which would prove nothing about what gets sent.
    draft = mock(() =>
      Promise.resolve({
        metrics: [],
        unresolved: [],
        checklist: [CHECK],
        journal: JOURNAL,
      })
    );
    getCategories = mock(() => Promise.resolve([SPORT, VITAMINS]));
    render(<DailySummaryPage />);
    fireEvent.change(screen.getByLabelText('Как прошёл день'), {
      target: { value: 'выпил B12' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Разобрать день/ }));
    await waitFor(() => expect(screen.getByLabelText(CHECKLIST_TITLE)).toBeDefined());

    fireEvent.click(screen.getByLabelText('Отметить выпил B12'));
    fireEvent.click(screen.getByRole('button', { name: /Записать выбранное/ }));

    await waitFor(() => expect(applyPlan).toHaveBeenCalledTimes(1));
    expect(applyPlan.mock.calls[0][2]).toEqual([]);
  });

  it('counts the unchecked tick out of the write button', async () => {
    await renderWithChecklist();

    fireEvent.click(screen.getByLabelText('Отметить выпил B12'));

    expect(
      screen.getByRole('button', { name: /Записать выбранное \(0\)/ })
    ).toBeDefined();
  });

  it('renders no section at all when the plan ticks nothing', async () => {
    await renderWithPlan();

    expect(screen.queryByLabelText(CHECKLIST_TITLE)).toBeNull();
  });
});
