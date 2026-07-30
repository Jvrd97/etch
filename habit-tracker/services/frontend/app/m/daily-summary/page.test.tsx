// [review:need-review] PHASE-01/74-daily-summary-journal
// summary: mobile day-summary tests — same full path as the desktop screen (text -> plan -> unchecked rows -> journal op -> apply), landing on the mobile Entries twin, plus the unresolved section and the LLM error with Retry

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import type { Category, DailySummaryPlan, JournalOp, LogMetricOp } from '@/lib/api';

const TIMESTAMP = '2026-07-30T00:00:00Z';

/** The catalogue the plan's ids resolve against: names are what the card shows. */
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
      name: 'Сон',
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
      value: 7,
      source_text: 'спал 7 часов',
      uncertain: true,
      implausible: false,
    },
  ],
  unresolved: [{ text: 'погулял с собакой', reason: 'нет категории' }],
  journal: null,
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
// first time anything links against it and shares that registry across the run.
mock.module('@/lib/api', () => ({
  dailySummaryAPI: {
    draft: (transcript: string, entryDate: string) => draft(transcript, entryDate),
    apply: (
      entryDate: string,
      metrics: LogMetricOp[],
      journal: JournalOp | null,
      idempotencyKey: string
    ) => applyPlan(entryDate, metrics, journal, idempotencyKey),
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
  usePathname: () => '/m/daily-summary',
  useRouter: () => ({ push: (href: string) => pushRoute(href), replace: () => {} }),
}));

const { default: MobileDailySummaryPage } = await import('./page');

async function renderWithPlan() {
  render(<MobileDailySummaryPage />);
  fireEvent.change(screen.getByLabelText('Как прошёл день'), {
    target: { value: 'отжался 30 раз, спал 7 часов, погулял с собакой' },
  });
  fireEvent.click(screen.getByRole('button', { name: /Разобрать день/ }));
  await waitFor(() =>
    expect(screen.getByLabelText('Записать отжался 30 раз')).toBeDefined()
  );
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

describe('/m/daily-summary', () => {
  it('checks a confident metric and leaves an uncertain one alone', async () => {
    await renderWithPlan();

    expect(
      (screen.getByLabelText('Записать отжался 30 раз') as HTMLInputElement).checked
    ).toBe(true);
    expect(
      (screen.getByLabelText('Записать спал 7 часов') as HTMLInputElement).checked
    ).toBe(false);
  });

  it('names the category and the field each metric would go into', async () => {
    await renderWithPlan();

    await waitFor(() => expect(screen.getByText(/Спорт · Отжимания/)).toBeDefined());
    expect(screen.getByText(/Спорт · Сон/)).toBeDefined();
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

  it('writes only the checked metrics, then lands on the mobile Entries screen', async () => {
    await renderWithPlan();

    fireEvent.click(screen.getByLabelText('Записать спал 7 часов'));
    fireEvent.click(screen.getByRole('button', { name: /Записать выбранное/ }));

    await waitFor(() => expect(applyPlan).toHaveBeenCalledTimes(1));
    const metrics = applyPlan.mock.calls[0][1] as LogMetricOp[];
    expect(metrics).toHaveLength(2);
    await waitFor(() => expect(pushRoute).toHaveBeenCalledWith('/m/entries'));
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

  it('sends the day text as an append by default', async () => {
    draft = mock(() => Promise.resolve({ ...PLAN, journal: JOURNAL }));
    await renderWithPlan();

    fireEvent.click(screen.getByRole('button', { name: /Записать выбранное/ }));

    await waitFor(() => expect(applyPlan).toHaveBeenCalledTimes(1));
    expect((applyPlan.mock.calls[0][2] as JournalOp).mode).toBe('append');
  });

  it('replaces the day text only after the user checks it', async () => {
    draft = mock(() => Promise.resolve({ ...PLAN, journal: JOURNAL }));
    await renderWithPlan();

    fireEvent.click(screen.getByLabelText('Заменить текст'));
    fireEvent.click(screen.getByRole('button', { name: /Записать выбранное/ }));

    await waitFor(() => expect(applyPlan).toHaveBeenCalledTimes(1));
    expect((applyPlan.mock.calls[0][2] as JournalOp).mode).toBe('replace');
  });

  it('offers a retry and keeps the text when the model is unreachable', async () => {
    draft = mock(() => Promise.reject(new Error('LLM backend unavailable')));
    render(<MobileDailySummaryPage />);
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
