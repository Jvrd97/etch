// [review:need-review] PHASE-01/75-daily-summary-checklist
// summary: tests for useDailySummary — text/date -> plan -> checkbox edits (metrics and checklist ticks) -> the journal op (append by default, replace opt-in) -> one idempotent apply

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import type {
  Category,
  CheckOp,
  DailySummaryPlan,
  JournalOp,
  LogMetricOp,
} from '@/lib/api';

const TIMESTAMP = '2026-07-30T00:00:00Z';

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
  ],
};

function metric(overrides: Partial<LogMetricOp> = {}): LogMetricOp {
  return {
    op: 'log_metric',
    category_id: 1,
    field_id: 2,
    value: 30,
    source_text: 'отжался 30 раз',
    uncertain: false,
    implausible: false,
    ...overrides,
  };
}

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

function check(overrides: Partial<CheckOp> = {}): CheckOp {
  return {
    op: 'check',
    category_id: 4,
    field_id: 9,
    source_text: 'выпил B12',
    uncertain: false,
    ...overrides,
  };
}

function journalOp(overrides: Partial<JournalOp> = {}): JournalOp {
  return {
    op: 'write_journal',
    title: 'Разбор дня',
    content: '## Спорт\n\nОтжался 30 раз.',
    mood: null,
    tags: null,
    mode: 'create',
    existing_entry_id: null,
    ...overrides,
  };
}

const PLAN: DailySummaryPlan = { metrics: [metric()], unresolved: [], journal: null };

const TODAY = '2026-07-30';

let draft: ReturnType<typeof mock>;
let applyPlan: ReturnType<typeof mock>;
let getCategories: ReturnType<typeof mock>;

// The whole `@/lib/api` surface is declared because bun fixes a module's export
// names on first link and shares them across the run; a partial mock here would
// delete the other APIs for whichever file loads later.
mock.module('@/lib/api', () => ({
  // The quick-mark directory and its one write path (#121). Present in every
  // api mock for the reason named above: bun fixes a module's export names on
  // first link, so a mock that omits an export deletes it for whoever links next.
  quickMarksAPI: {
    list: () => Promise.resolve([]),
    tap: () => Promise.resolve(null),
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
  insightsAPI: {
    getAll: () => Promise.resolve([]),
    getById: () => Promise.resolve(null),
    create: () => Promise.resolve(null),
  },
  tableAPI: { get: () => Promise.resolve({ days: [] }) },
  journalAPI: { getAll: () => Promise.resolve({ total: 0, items: [] }) },
}));

const { useDailySummary } = await import('./useDailySummary');

/** Render the hook and drive it to a settled plan built from `plan`. */
async function renderWithPlan(plan: DailySummaryPlan, onApplied = mock(() => {})) {
  draft = mock(() => Promise.resolve(plan));
  const view = renderHook(() => useDailySummary({ onApplied, today: TODAY }));
  act(() => view.result.current.setTranscript('отжался 30 раз'));
  await act(async () => {
    await view.result.current.generate();
  });
  await waitFor(() => expect(view.result.current.draft.status).toBe('done'));
  return { ...view, onApplied };
}

beforeEach(() => {
  draft = mock(() => Promise.resolve(PLAN));
  applyPlan = mock(() => Promise.resolve({ entry_ids: [1] }));
  getCategories = mock(() => Promise.resolve([SPORT]));
});

afterEach(() => {
  cleanup();
});

describe('useDailySummary', () => {
  it('starts idle, on today, with nothing to send', async () => {
    const { result } = renderHook(() =>
      useDailySummary({ onApplied: () => {}, today: TODAY })
    );

    expect(result.current.draft.status).toBe('idle');
    expect(result.current.entryDate).toBe(TODAY);
    expect(result.current.enabledCount).toBe(0);
    expect(result.current.canGenerate).toBe(false);
    // The catalogue lands on mount; settling it here keeps its state update
    // inside the test rather than after it.
    await waitFor(() =>
      expect(result.current.resolveLabel(metric()).categoryName).toBe('Спорт')
    );
  });

  it('refuses to generate from whitespace alone', async () => {
    const { result } = renderHook(() =>
      useDailySummary({ onApplied: () => {}, today: TODAY })
    );

    act(() => result.current.setTranscript('   '));
    expect(result.current.canGenerate).toBe(false);
    await act(async () => {
      await result.current.generate();
    });

    expect(draft).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(result.current.resolveLabel(metric()).categoryName).toBe('Спорт')
    );
  });

  it('sends the trimmed text with the chosen date', async () => {
    draft = mock(() => Promise.resolve(PLAN));
    const { result } = renderHook(() =>
      useDailySummary({ onApplied: () => {}, today: TODAY })
    );

    act(() => result.current.setEntryDate('2026-07-29'));
    act(() => result.current.setTranscript('  отжался 30 раз  '));
    await act(async () => {
      await result.current.generate();
    });

    expect(draft.mock.calls[0]).toEqual(['отжался 30 раз', '2026-07-29']);
  });

  it('opts a confidently placed metric in', async () => {
    const { result } = await renderWithPlan(PLAN);

    expect(result.current.metricStates[0].enabled).toBe(true);
    expect(result.current.enabledCount).toBe(1);
  });

  it('leaves an uncertain or implausible metric out', async () => {
    const plan: DailySummaryPlan = {
      metrics: [
        metric(),
        metric({ uncertain: true }),
        metric({ implausible: true }),
      ],
      unresolved: [],
    };
    const { result } = await renderWithPlan(plan);

    expect(result.current.metricStates.map((s) => s.enabled)).toEqual([
      true,
      false,
      false,
    ]);
    expect(result.current.enabledCount).toBe(1);
  });

  it('exposes what the model could not place, and creates nothing from it', async () => {
    const plan: DailySummaryPlan = {
      metrics: [],
      unresolved: [{ text: 'погулял с собакой', reason: 'нет категории' }],
    };
    const { result } = await renderWithPlan(plan);

    expect(result.current.unresolved).toHaveLength(1);
    expect(result.current.enabledCount).toBe(0);
  });

  it('applies only the checked metrics, under the chosen date', async () => {
    const plan: DailySummaryPlan = {
      metrics: [metric(), metric({ field_id: 3, value: 10 })],
      unresolved: [],
    };
    const { result, onApplied } = await renderWithPlan(plan);

    act(() => result.current.toggleMetric(1, false));
    await act(async () => {
      await result.current.apply();
    });

    expect(applyPlan).toHaveBeenCalledTimes(1);
    const [date, sent] = applyPlan.mock.calls[0] as [string, LogMetricOp[]];
    expect(date).toBe(TODAY);
    expect(sent).toHaveLength(1);
    expect(sent[0].field_id).toBe(2);
    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1));
  });

  it('does not call the API when nothing is checked', async () => {
    const { result, onApplied } = await renderWithPlan({
      metrics: [metric({ uncertain: true })],
      unresolved: [],
    });

    await act(async () => {
      await result.current.apply();
    });

    expect(applyPlan).not.toHaveBeenCalled();
    expect(onApplied).not.toHaveBeenCalled();
  });

  it('reports a failed draft and stays retryable with the text intact', async () => {
    draft = mock(() => Promise.reject(new Error('LLM backend unavailable')));
    const { result } = renderHook(() =>
      useDailySummary({ onApplied: () => {}, today: TODAY })
    );

    act(() => result.current.setTranscript('отжался 30 раз'));
    await act(async () => {
      await result.current.generate();
    });

    expect(result.current.draft).toEqual({
      status: 'error',
      message: 'LLM backend unavailable',
    });
    expect(result.current.transcript).toBe('отжался 30 раз');
    expect(result.current.canGenerate).toBe(true);
  });

  it('keeps the plan and the text on screen when applying fails', async () => {
    applyPlan = mock(() => Promise.reject(new Error('unknown category_id 4')));
    const { result, onApplied } = await renderWithPlan(PLAN);

    await act(async () => {
      await result.current.apply();
    });

    expect(result.current.applyState).toEqual({
      status: 'error',
      message: 'unknown category_id 4',
    });
    expect(result.current.draft.status).toBe('done');
    expect(result.current.transcript).toBe('отжался 30 раз');
    expect(onApplied).not.toHaveBeenCalled();
  });

  it('names the category and the field a metric resolved to', async () => {
    const { result } = await renderWithPlan(PLAN);

    await waitFor(() =>
      expect(result.current.resolveLabel(metric())).toEqual({
        categoryName: 'Спорт',
        fieldName: 'Отжимания',
      })
    );
  });

  it('falls back to the ids when the catalogue has no such category or field', async () => {
    const { result } = await renderWithPlan(PLAN);
    await waitFor(() =>
      expect(result.current.resolveLabel(metric()).categoryName).toBe('Спорт')
    );

    expect(result.current.resolveLabel(metric({ category_id: 99 }))).toEqual({
      categoryName: 'категория #99',
      fieldName: 'поле #2',
    });
    expect(result.current.resolveLabel(metric({ field_id: 77 })).fieldName).toBe(
      'поле #77'
    );
  });

  it('keeps the flow usable when the catalogue cannot be loaded', async () => {
    getCategories = mock(() => Promise.reject(new Error('offline')));
    const { result } = await renderWithPlan(PLAN);

    expect(result.current.draft.status).toBe('done');
    expect(result.current.resolveLabel(metric())).toEqual({
      categoryName: 'категория #1',
      fieldName: 'поле #2',
    });
  });

  it('brings the day text in checked, with replacement offered but off', async () => {
    const journal = journalOp({ mode: 'append', existing_entry_id: 7 });
    const { result } = await renderWithPlan({ ...PLAN, journal });

    expect(result.current.journal).toEqual(journal);
    expect(result.current.journalEnabled).toBe(true);
    expect(result.current.journalReplace).toBe(false);
    expect(result.current.canReplaceJournal).toBe(true);
  });

  it('offers no replacement when the day has nothing to replace', async () => {
    const { result } = await renderWithPlan({ ...PLAN, journal: journalOp() });

    expect(result.current.canReplaceJournal).toBe(false);
  });

  it('appends the day text by default', async () => {
    const journal = journalOp({ mode: 'append', existing_entry_id: 7 });
    const { result } = await renderWithPlan({ ...PLAN, journal });

    await act(async () => {
      await result.current.apply();
    });

    const sent = applyPlan.mock.calls[0][3] as JournalOp;
    expect(sent.mode).toBe('append');
    expect(sent.existing_entry_id).toBe(7);
  });

  it('turns the operation into a replacement only when asked', async () => {
    const journal = journalOp({ mode: 'append', existing_entry_id: 7 });
    const { result } = await renderWithPlan({ ...PLAN, journal });

    act(() => result.current.setJournalReplace(true));
    await act(async () => {
      await result.current.apply();
    });

    expect((applyPlan.mock.calls[0][3] as JournalOp).mode).toBe('replace');
  });

  it('sends no journal at all once it is unchecked', async () => {
    const { result } = await renderWithPlan({ ...PLAN, journal: journalOp() });

    act(() => result.current.setJournalEnabled(false));
    await act(async () => {
      await result.current.apply();
    });

    expect(applyPlan.mock.calls[0][3]).toBeNull();
  });

  it('writes the day text even when every metric is left out', async () => {
    const { result } = await renderWithPlan({
      metrics: [metric({ uncertain: true })],
      unresolved: [],
      journal: journalOp(),
    });

    expect(result.current.canApply).toBe(true);
    await act(async () => {
      await result.current.apply();
    });

    expect(applyPlan).toHaveBeenCalledTimes(1);
    expect(applyPlan.mock.calls[0][1]).toEqual([]);
  });

  it('has nothing to apply once both halves are switched off', async () => {
    const { result } = await renderWithPlan({
      metrics: [metric({ uncertain: true })],
      unresolved: [],
      journal: journalOp(),
    });

    act(() => result.current.setJournalEnabled(false));
    expect(result.current.canApply).toBe(false);

    await act(async () => {
      await result.current.apply();
    });
    expect(applyPlan).not.toHaveBeenCalled();
  });

  it('retries one plan under one idempotency key, and a new plan under a new one', async () => {
    applyPlan = mock(() => Promise.reject(new Error('boom')));
    const { result } = await renderWithPlan(PLAN);

    await act(async () => {
      await result.current.apply();
    });
    await act(async () => {
      await result.current.apply();
    });
    const firstKey = applyPlan.mock.calls[0][4] as string;
    expect(firstKey).toBeTruthy();
    expect(applyPlan.mock.calls[1][4]).toBe(firstKey);

    await act(async () => {
      await result.current.generate();
    });
    await act(async () => {
      await result.current.apply();
    });

    expect(applyPlan.mock.calls[2][4]).not.toBe(firstKey);
  });

  it('mints a new idempotency key when the date is changed', async () => {
    applyPlan = mock(() => Promise.reject(new Error('boom')));
    const { result } = await renderWithPlan(PLAN);

    await act(async () => {
      await result.current.apply();
    });
    const firstKey = applyPlan.mock.calls[0][4] as string;

    await act(() => {
      result.current.setEntryDate('2026-07-31');
    });
    await act(async () => {
      await result.current.apply();
    });

    expect(applyPlan.mock.calls[1][0]).toBe('2026-07-31');
    expect(applyPlan.mock.calls[1][4]).not.toBe(firstKey);
  });

  it('clears a stale apply error when a new plan is generated', async () => {
    applyPlan = mock(() => Promise.reject(new Error('unknown category_id 4')));
    const { result } = await renderWithPlan(PLAN);
    await act(async () => {
      await result.current.apply();
    });
    expect(result.current.applyState.status).toBe('error');

    draft = mock(() => Promise.resolve(PLAN));
    await act(async () => {
      await result.current.generate();
    });

    expect(result.current.applyState).toEqual({ status: 'idle' });
  });
});

describe('useDailySummary checklist', () => {
  it('opts a confident tick in and counts it alongside the metrics', async () => {
    const { result } = await renderWithPlan({ ...PLAN, checklist: [check()] });

    expect(result.current.checklist).toHaveLength(1);
    expect(result.current.checkStates[0].enabled).toBe(true);
    expect(result.current.enabledCount).toBe(2);
  });

  it('leaves an uncertain tick out', async () => {
    const { result } = await renderWithPlan({
      metrics: [],
      unresolved: [],
      checklist: [check({ uncertain: true })],
    });

    expect(result.current.checkStates[0].enabled).toBe(false);
    expect(result.current.canApply).toBe(false);
  });

  it('sends only the ticks left checked', async () => {
    const { result } = await renderWithPlan({
      metrics: [],
      unresolved: [],
      checklist: [check(), check({ field_id: 10, source_text: 'выпил D3' })],
    });

    act(() => result.current.toggleCheck(1, false));
    await act(async () => {
      await result.current.apply();
    });

    const sent = applyPlan.mock.calls[0][2] as CheckOp[];
    expect(sent).toHaveLength(1);
    expect(sent[0].field_id).toBe(9);
  });

  it('applies a day that is nothing but a tick', async () => {
    const { result, onApplied } = await renderWithPlan({
      metrics: [],
      unresolved: [],
      checklist: [check()],
    });

    expect(result.current.canApply).toBe(true);
    await act(async () => {
      await result.current.apply();
    });

    expect(applyPlan).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1));
  });

  it('sends an empty checklist for a plan that ticks nothing', async () => {
    const { result } = await renderWithPlan(PLAN);

    await act(async () => {
      await result.current.apply();
    });

    // Empty, never a map of falses: an absent box must reach the server as
    // "not mentioned", which is the only reading that cannot untick anything.
    expect(applyPlan.mock.calls[0][2]).toEqual([]);
  });

  it('names the category and box behind a tick', async () => {
    getCategories = mock(() => Promise.resolve([SPORT, VITAMINS]));
    const { result } = await renderWithPlan({ ...PLAN, checklist: [check()] });

    await waitFor(() =>
      expect(result.current.resolveLabel(check()).categoryName).toBe('Витамины')
    );
    expect(result.current.resolveLabel(check()).fieldName).toBe('B12');
  });

  it('reads a draft without a checklist as no ticks at all', async () => {
    const { result } = await renderWithPlan(PLAN);

    expect(result.current.checklist).toEqual([]);
    expect(result.current.checkStates).toEqual([]);
  });
});
