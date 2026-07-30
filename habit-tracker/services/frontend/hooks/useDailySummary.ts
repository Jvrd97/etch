'use client';
// [review:need-review] PHASE-01/73-daily-summary-metrics-vertical
// summary: single owner of the day-summary flow — text + date, the LLM draft, per-metric opt-in, and the transactional apply; both day-summary screens differ only in markup and in where they navigate afterwards

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  categoriesAPI,
  dailySummaryAPI,
  type Category,
  type DailySummaryPlan,
  type LogMetricOp,
} from '@/lib/api';
import { todayISO } from '@/lib/date';

export const DRAFT_ERROR = 'Не удалось разобрать день';
export const APPLY_ERROR = 'Не удалось записать день';

/**
 * Heading and accessible name of the "could not be placed" list.
 *
 * Both screens render that section and both tests reach for it by name, so the
 * wording lives beside the flow that produces it rather than in either page.
 */
export const UNRESOLVED_TITLE = 'Не нашлось категории';

/**
 * Accessible name of a metric's checkbox: what the model heard, verbatim.
 *
 * Spelled here rather than in either screen because both render the same
 * control and the tests assert on the name — and named exports out of an App
 * Router `page.tsx` are a contract Next does not promise to keep.
 */
export function metricCheckboxLabel(metric: LogMetricOp): string {
  return `Записать ${metric.source_text}`;
}

/**
 * What a metric's ids mean, in words the user recognises.
 *
 * The plan resolves by id and only by id (#57), so the ids are the truth and
 * this is a display layer over them: a preview that reads "категория #4 · поле
 * #9" asks the user to approve a write they cannot check.
 */
export interface MetricLabel {
  categoryName: string;
  fieldName: string;
}

/**
 * Shown for an id the catalogue does not explain.
 *
 * A category deleted between the draft and the preview, or a catalogue request
 * that failed, leaves the id as the only thing known about the metric — which
 * is still worth showing, and is exactly what the apply will send.
 */
function unknownCategoryName(id: number): string {
  return `категория #${id}`;
}

function unknownFieldName(id: number): string {
  return `поле #${id}`;
}

/** Per-metric editable state in the preview: whether it ships. */
export interface MetricState {
  enabled: boolean;
}

/** Where the plan request stands. The plan itself only exists in `done`. */
export type DraftState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'done'; plan: DailySummaryPlan };

/** Where the apply stands. A finished apply hands off to `onApplied`. */
export type ApplyState =
  | { status: 'idle' }
  | { status: 'applying' }
  | { status: 'error'; message: string };

export interface UseDailySummaryResult {
  transcript: string;
  setTranscript: (text: string) => void;
  /** `YYYY-MM-DD` the day is filed under; defaults to today's local date. */
  entryDate: string;
  setEntryDate: (date: string) => void;
  draft: DraftState;
  applyState: ApplyState;
  /** One entry per metric of the current plan, index-aligned with it. */
  metricStates: MetricState[];
  /** What the model heard but could not place. Read-only: it creates nothing. */
  unresolved: DailySummaryPlan['unresolved'];
  /** How many metrics would be written right now; also the apply button's guard. */
  enabledCount: number;
  /** False while the text is blank or a draft is already in flight. */
  canGenerate: boolean;
  /** Ask the LLM for a plan. A blank text is a no-op, not a request. */
  generate: () => Promise<void>;
  /** The category and field names behind a metric's ids, ids as the fallback. */
  resolveLabel: (metric: LogMetricOp) => MetricLabel;
  /** Check or uncheck one metric of the preview. */
  toggleMetric: (index: number, enabled: boolean) => void;
  /** Write the checked metrics as one transaction, then hand off to `onApplied`. */
  apply: () => Promise<void>;
}

export interface UseDailySummaryOptions {
  /**
   * Called once the day went in. The two shells land on different routes
   * (`/entries` and `/m/entries`), which is the only thing about this flow
   * that differs between them.
   */
  onApplied: () => void;
  /** Today's date, injectable so tests can pin the day instead of the clock. */
  today?: string;
}

/**
 * Default checkbox state per metric: a confidently placed one is opted in, while
 * anything the model flagged as uncertain or implausible starts off.
 *
 * The asymmetry is the point — a metric that lands in the wrong category is
 * undone one entry at a time through Entries, so the doubtful ones have to cost
 * a deliberate click rather than an unnoticed one.
 */
function initialMetricStates(plan: DailySummaryPlan): MetricState[] {
  return plan.metrics.map((metric) => ({
    enabled: !metric.uncertain && !metric.implausible,
  }));
}

/** The apply payload: the metrics left checked, in plan order. */
function selectedMetrics(plan: DailySummaryPlan, states: MetricState[]): LogMetricOp[] {
  return plan.metrics.filter((_, i) => states[i]?.enabled);
}

export function useDailySummary({
  onApplied,
  today,
}: UseDailySummaryOptions): UseDailySummaryResult {
  const [transcript, setTranscript] = useState('');
  const [entryDate, setEntryDate] = useState(today ?? todayISO());
  const [draft, setDraft] = useState<DraftState>({ status: 'idle' });
  const [metricStates, setMetricStates] = useState<MetricState[]>([]);
  const [applyState, setApplyState] = useState<ApplyState>({ status: 'idle' });
  const [categories, setCategories] = useState<Category[]>([]);

  // The catalogue is fetched for display only, so a failure is swallowed rather
  // than banner-ed: the plan is still valid, the preview still applies, and the
  // rows simply keep reading as ids. Turning this into a blocking error would
  // stop a day from being recorded over a naming problem.
  useEffect(() => {
    let cancelled = false;
    categoriesAPI
      .getAll()
      .then((loaded) => {
        if (!cancelled) setCategories(loaded);
      })
      .catch(() => {
        if (!cancelled) setCategories([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // One pass over the catalogue instead of one scan per rendered row; the plan
  // is small, but the lookup is what every metric row calls on every render.
  // A field is keyed by its owning category too, the same pairing the backend
  // validates: a field_id that belongs to another category is not explained by
  // that category's name, it is shown as the unresolved id it effectively is.
  const namesById = useMemo(() => {
    const categoryNames = new Map<number, string>();
    const fieldNames = new Map<string, string>();
    for (const category of categories) {
      categoryNames.set(category.id, category.name);
      for (const field of category.fields) {
        fieldNames.set(`${category.id}:${field.id}`, field.name);
      }
    }
    return { categoryNames, fieldNames };
  }, [categories]);

  const resolveLabel = useCallback(
    (metric: LogMetricOp): MetricLabel => ({
      categoryName:
        namesById.categoryNames.get(metric.category_id) ??
        unknownCategoryName(metric.category_id),
      fieldName:
        namesById.fieldNames.get(`${metric.category_id}:${metric.field_id}`) ??
        unknownFieldName(metric.field_id),
    }),
    [namesById]
  );

  const generate = useCallback(async () => {
    const text = transcript.trim();
    if (text.length === 0) return;
    setDraft({ status: 'loading' });
    // A new plan retires whatever the previous one failed to write: leaving the
    // old banner up would blame the fresh preview for the old plan's rejection.
    setApplyState({ status: 'idle' });
    try {
      const plan = await dailySummaryAPI.draft(text, entryDate);
      setMetricStates(initialMetricStates(plan));
      setDraft({ status: 'done', plan });
    } catch (err) {
      // The text stays in state on purpose: retelling the day because the
      // backend was down once is the one thing this screen must never ask for.
      setDraft({
        status: 'error',
        message: err instanceof Error ? err.message : DRAFT_ERROR,
      });
    }
  }, [transcript, entryDate]);

  const toggleMetric = useCallback((index: number, enabled: boolean) => {
    setMetricStates((prev) => prev.map((s, i) => (i === index ? { enabled } : s)));
  }, []);

  const apply = useCallback(async () => {
    if (draft.status !== 'done') return;
    const metrics = selectedMetrics(draft.plan, metricStates);
    if (metrics.length === 0) return;
    setApplyState({ status: 'applying' });
    try {
      await dailySummaryAPI.apply(entryDate, metrics);
      onApplied();
    } catch (err) {
      // Plan and text both survive: the apply is all-or-nothing server-side, so
      // the same screen can be resubmitted as-is once the cause is fixed.
      setApplyState({
        status: 'error',
        message: err instanceof Error ? err.message : APPLY_ERROR,
      });
    }
  }, [draft, metricStates, entryDate, onApplied]);

  return {
    transcript,
    setTranscript,
    entryDate,
    setEntryDate,
    draft,
    applyState,
    metricStates,
    unresolved: draft.status === 'done' ? draft.plan.unresolved : [],
    enabledCount: metricStates.filter((s) => s.enabled).length,
    canGenerate: transcript.trim().length > 0 && draft.status !== 'loading',
    generate,
    resolveLabel,
    toggleMetric,
    apply,
  };
}
