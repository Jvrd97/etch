// [review:need-review] PHASE-01/74-daily-summary-journal
// summary: tests for useDailySummary — text/date -> plan -> checkbox edits -> the journal op (append by default, replace opt-in) -> one idempotent apply

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import type { Category, DailySummaryPlan, JournalOp, LogMetricOp } from '@/lib/api';

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

    const sent = applyPlan.mock.calls[0][2] as JournalOp;
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

    expect((applyPlan.mock.calls[0][2] as JournalOp).mode).toBe('replace');
  });

  it('sends no journal at all once it is unchecked', async () => {
    const { result } = await renderWithPlan({ ...PLAN, journal: journalOp() });

    act(() => result.current.setJournalEnabled(false));
    await act(async () => {
      await result.current.apply();
    });

    expect(applyPlan.mock.calls[0][2]).toBeNull();
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
    const firstKey = applyPlan.mock.calls[0][3] as string;
    expect(firstKey).toBeTruthy();
    expect(applyPlan.mock.calls[1][3]).toBe(firstKey);

    await act(async () => {
      await result.current.generate();
    });
    await act(async () => {
      await result.current.apply();
    });

    expect(applyPlan.mock.calls[2][3]).not.toBe(firstKey);
  });

  it('mints a new idempotency key when the date is changed', async () => {
    applyPlan = mock(() => Promise.reject(new Error('boom')));
    const { result } = await renderWithPlan(PLAN);

    await act(async () => {
      await result.current.apply();
    });
    const firstKey = applyPlan.mock.calls[0][3] as string;

    await act(() => {
      result.current.setEntryDate('2026-07-31');
    });
    await act(async () => {
      await result.current.apply();
    });

    expect(applyPlan.mock.calls[1][0]).toBe('2026-07-31');
    expect(applyPlan.mock.calls[1][3]).not.toBe(firstKey);
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
