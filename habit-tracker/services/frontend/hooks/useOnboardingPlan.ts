'use client';
// [review:need-review] PHASE-01/62-mobile-onboarding-twin
// summary: single owner of the voice-category-builder flow — transcript, LLM draft, per-operation opt-in with editable names, and the transactional batch apply; both onboarding screens differ only in markup and in where they navigate afterwards

import { useCallback, useState } from 'react';
import {
  categoriesAPI,
  onboardingAPI,
  type OnboardingPlan,
  type PlanOperation,
} from '@/lib/api';

export const DRAFT_ERROR = 'Не удалось построить план';
export const APPLY_ERROR = 'Не удалось создать категории';

/**
 * Per-operation editable state in the preview. `name` only matters for
 * `create_category` ops; `add_field` ops ignore it.
 */
export interface OpState {
  enabled: boolean;
  name: string;
}

/** Where the plan request stands. The plan itself only exists in `done`. */
export type DraftState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'done'; plan: OnboardingPlan };

/** Where the batch apply stands. A finished apply hands off to `onApplied`. */
export type ApplyState =
  | { status: 'idle' }
  | { status: 'applying' }
  | { status: 'error'; message: string };

export interface UseOnboardingPlanResult {
  transcript: string;
  setTranscript: (text: string) => void;
  draft: DraftState;
  applyState: ApplyState;
  /** One entry per operation of the current plan, index-aligned with it. */
  opStates: OpState[];
  /** How many operations would be sent right now; also the apply button's guard. */
  enabledCount: number;
  /** False while the transcript is blank or a draft is already in flight. */
  canGenerate: boolean;
  /** Ask the LLM for a plan. A blank transcript is a no-op, not a request. */
  generate: () => Promise<void>;
  /** Edit one preview row: its checkbox, its name, or both. */
  updateOp: (index: number, patch: Partial<OpState>) => void;
  /** Post the enabled operations as one transaction, then hand off to `onApplied`. */
  apply: () => Promise<void>;
}

export interface UseOnboardingPlanOptions {
  /**
   * Called once the batch went through. The two shells land on different
   * routes (`/categories` and `/m/categories`), which is the only thing about
   * this flow that differs between them.
   */
  onApplied: () => void;
}

/**
 * Default checkbox state per operation: a fresh category without a name clash
 * is opted in (a stray new category is undone by one delete), while `add_field`
 * and anything flagged as a conflict start off — those touch data that already
 * exists, so they need a deliberate click.
 */
function initialOpStates(plan: OnboardingPlan): OpState[] {
  return plan.operations.map((op) => {
    if (op.op === 'create_category') {
      return { enabled: !op.name_conflict, name: op.name };
    }
    return { enabled: false, name: '' };
  });
}

/** The batch payload: the ops left enabled, `create_category` carrying its edited name. */
function selectedOperations(plan: OnboardingPlan, states: OpState[]): PlanOperation[] {
  const selected: PlanOperation[] = [];
  plan.operations.forEach((op, i) => {
    const state = states[i];
    if (!state?.enabled) return;
    selected.push(op.op === 'create_category' ? { ...op, name: state.name } : op);
  });
  return selected;
}

export function useOnboardingPlan({
  onApplied,
}: UseOnboardingPlanOptions): UseOnboardingPlanResult {
  const [transcript, setTranscript] = useState('');
  const [draft, setDraft] = useState<DraftState>({ status: 'idle' });
  const [opStates, setOpStates] = useState<OpState[]>([]);
  const [applyState, setApplyState] = useState<ApplyState>({ status: 'idle' });

  const generate = useCallback(async () => {
    const text = transcript.trim();
    if (text.length === 0) return;
    setDraft({ status: 'loading' });
    // A new plan retires whatever the previous one failed to apply: leaving the
    // old banner up would blame the fresh preview for the old plan's clash.
    setApplyState({ status: 'idle' });
    try {
      const plan = await onboardingAPI.draft(text);
      setOpStates(initialOpStates(plan));
      setDraft({ status: 'done', plan });
    } catch (err) {
      setDraft({
        status: 'error',
        message: err instanceof Error ? err.message : DRAFT_ERROR,
      });
    }
  }, [transcript]);

  const updateOp = useCallback((index: number, patch: Partial<OpState>) => {
    setOpStates((prev) => prev.map((s, i) => (i === index ? { ...s, ...patch } : s)));
  }, []);

  const apply = useCallback(async () => {
    if (draft.status !== 'done') return;
    const operations = selectedOperations(draft.plan, opStates);
    if (operations.length === 0) return;
    setApplyState({ status: 'applying' });
    try {
      await categoriesAPI.applyBatch(operations);
      onApplied();
    } catch (err) {
      setApplyState({
        status: 'error',
        message: err instanceof Error ? err.message : APPLY_ERROR,
      });
    }
  }, [draft, opStates, onApplied]);

  return {
    transcript,
    setTranscript,
    draft,
    applyState,
    opStates,
    enabledCount: opStates.filter((s) => s.enabled).length,
    canGenerate: transcript.trim().length > 0 && draft.status !== 'loading',
    generate,
    updateOp,
    apply,
  };
}
