// [review:need-review] PHASE-01/62-mobile-onboarding-twin
// summary: tests for useOnboardingPlan — the single owner of draft/preview/apply for both onboarding screens: default opt-in rules, name edits, the batch payload, and error handling on both requests

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import type { CreateCategoryOp, OnboardingPlan, PlanOperation } from '@/lib/api';

function createOp(overrides: Partial<CreateCategoryOp> = {}): CreateCategoryOp {
  return {
    op: 'create_category',
    name: 'Sleep',
    display_mode: 'form',
    streak_mode: 'build',
    fields: [{ name: 'Hours', field_type: 'number', is_required: false, order: 0 }],
    name_conflict: false,
    ...overrides,
  };
}

const ADD_FIELD_OP: PlanOperation = {
  op: 'add_field',
  category_id: 3,
  field: { name: 'Pulse', field_type: 'number', is_required: false, order: 0 },
};

const PLAN: OnboardingPlan = { operations: [createOp()] };

let draft: ReturnType<typeof mock>;
let applyBatch: ReturnType<typeof mock>;

// The whole `@/lib/api` surface is declared because bun fixes a module's export
// names on first link and shares them across the run; a partial mock here would
// delete the other APIs for whichever file loads later.
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
    draft: () => Promise.resolve({ metrics: [], unresolved: [] }),
    apply: () => Promise.resolve({ entry_ids: [] }),
  },
  onboardingAPI: { draft: (text: string) => draft(text) },
  categoriesAPI: {
    getAll: () => Promise.resolve([]),
    getById: () => Promise.resolve(null),
    getStreak: () => Promise.resolve(null),
    create: () => Promise.resolve(null),
    update: () => Promise.resolve(null),
    delete: () => Promise.resolve(undefined),
    applyBatch: (operations: PlanOperation[]) => applyBatch(operations),
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
  journalAPI: { getAll: () => Promise.resolve({ items: [] }) },
}));

const { useOnboardingPlan } = await import('./useOnboardingPlan');

/** Render the hook and drive it to a settled plan built from `plan`. */
async function renderWithPlan(plan: OnboardingPlan, onApplied = mock(() => {})) {
  draft = mock(() => Promise.resolve(plan));
  const view = renderHook(() => useOnboardingPlan({ onApplied }));
  act(() => view.result.current.setTranscript('трекать сон'));
  await act(async () => {
    await view.result.current.generate();
  });
  await waitFor(() => expect(view.result.current.draft.status).toBe('done'));
  return { ...view, onApplied };
}

beforeEach(() => {
  draft = mock(() => Promise.resolve(PLAN));
  applyBatch = mock(() => Promise.resolve({ categories: [], fields: [] }));
});

afterEach(() => {
  cleanup();
});

describe('useOnboardingPlan', () => {
  it('starts idle with an empty transcript and nothing selected', () => {
    const { result } = renderHook(() => useOnboardingPlan({ onApplied: () => {} }));

    expect(result.current.draft.status).toBe('idle');
    expect(result.current.transcript).toBe('');
    expect(result.current.enabledCount).toBe(0);
    expect(result.current.canGenerate).toBe(false);
  });

  it('refuses to generate from whitespace alone', async () => {
    const { result } = renderHook(() => useOnboardingPlan({ onApplied: () => {} }));

    act(() => result.current.setTranscript('   '));
    expect(result.current.canGenerate).toBe(false);
    await act(async () => {
      await result.current.generate();
    });

    expect(draft).not.toHaveBeenCalled();
  });

  it('sends the trimmed transcript and keeps the returned plan', async () => {
    const { result } = await renderWithPlan(PLAN);

    expect(draft.mock.calls[0][0]).toBe('трекать сон');
    if (result.current.draft.status !== 'done') throw new Error('expected a plan');
    expect(result.current.draft.plan.operations).toHaveLength(1);
  });

  it('opts a clean new category in and leaves a name clash out', async () => {
    const plan: OnboardingPlan = {
      operations: [createOp(), createOp({ name: 'Sport', name_conflict: true })],
    };
    const { result } = await renderWithPlan(plan);

    expect(result.current.opStates.map((s) => s.enabled)).toEqual([true, false]);
    expect(result.current.enabledCount).toBe(1);
  });

  it('leaves an add_field operation out — it touches data that already exists', async () => {
    const { result } = await renderWithPlan({ operations: [ADD_FIELD_OP] });

    expect(result.current.opStates[0].enabled).toBe(false);
    expect(result.current.enabledCount).toBe(0);
  });

  it('applies only the enabled operations, carrying the edited name', async () => {
    const plan: OnboardingPlan = {
      operations: [createOp(), createOp({ name: 'Sport' }), ADD_FIELD_OP],
    };
    const { result, onApplied } = await renderWithPlan(plan);

    act(() => result.current.updateOp(1, { enabled: false }));
    act(() => result.current.updateOp(0, { name: 'Отбой' }));
    await act(async () => {
      await result.current.apply();
    });

    expect(applyBatch).toHaveBeenCalledTimes(1);
    const sent = applyBatch.mock.calls[0][0] as PlanOperation[];
    expect(sent).toHaveLength(1);
    expect(sent[0]).toMatchObject({ op: 'create_category', name: 'Отбой' });
    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1));
  });

  it('sends an add_field operation untouched once it is enabled', async () => {
    const { result } = await renderWithPlan({ operations: [ADD_FIELD_OP] });

    act(() => result.current.updateOp(0, { enabled: true }));
    await act(async () => {
      await result.current.apply();
    });

    expect(applyBatch.mock.calls[0][0]).toEqual([ADD_FIELD_OP]);
  });

  it('does not call the API when nothing is selected', async () => {
    const { result, onApplied } = await renderWithPlan({ operations: [ADD_FIELD_OP] });

    await act(async () => {
      await result.current.apply();
    });

    expect(applyBatch).not.toHaveBeenCalled();
    expect(onApplied).not.toHaveBeenCalled();
  });

  it('reports a failed draft and stays retryable', async () => {
    draft = mock(() => Promise.reject(new Error('LLM backend unavailable')));
    const { result } = renderHook(() => useOnboardingPlan({ onApplied: () => {} }));

    act(() => result.current.setTranscript('трекать сон'));
    await act(async () => {
      await result.current.generate();
    });

    expect(result.current.draft).toEqual({
      status: 'error',
      message: 'LLM backend unavailable',
    });
    expect(result.current.canGenerate).toBe(true);
  });

  it('keeps the plan on screen when applying it fails', async () => {
    applyBatch = mock(() => Promise.reject(new Error('name already taken')));
    const { result, onApplied } = await renderWithPlan(PLAN);

    await act(async () => {
      await result.current.apply();
    });

    expect(result.current.applyState).toEqual({
      status: 'error',
      message: 'name already taken',
    });
    expect(result.current.draft.status).toBe('done');
    expect(onApplied).not.toHaveBeenCalled();
  });

  it('clears a stale apply error when a new plan is generated', async () => {
    applyBatch = mock(() => Promise.reject(new Error('name already taken')));
    const { result } = await renderWithPlan(PLAN);
    await act(async () => {
      await result.current.apply();
    });
    expect(result.current.applyState.status).toBe('error');

    await act(async () => {
      await result.current.generate();
    });

    expect(result.current.applyState).toEqual({ status: 'idle' });
  });
});
