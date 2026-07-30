'use client';
// [review:need-review] PHASE-01/75-daily-summary-checklist
// summary: single owner of the day-summary flow — text + date, the LLM draft, per-metric and per-checkbox opt-in, the day's journal text (append by default, replace opt-in) and one idempotent transactional apply

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  categoriesAPI,
  dailySummaryAPI,
  type Category,
  type CheckOp,
  type DailySummaryPlan,
  type JournalOp,
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
 * Accessible name of the journal checkbox — the day's text as an opt-in.
 *
 * Named per mode rather than "Записать текст дня" for both, because the two
 * outcomes are genuinely different promises: one keeps what the morning left
 * behind, the other starts the day's page. Lives here so both screens and their
 * tests read the same wording.
 */
export function journalCheckboxLabel(journal: JournalOp): string {
  return journal.mode === 'create'
    ? 'Создать запись дня'
    : 'Дополнить запись дня';
}

/** Accessible name of the opt-in that turns an append into a replacement. */
export const JOURNAL_REPLACE_LABEL = 'Заменить текст';

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

/** Heading and accessible name of the checklist section of the preview. */
export const CHECKLIST_TITLE = 'Отметки в чек-листах';

/**
 * Accessible name of a tick's checkbox.
 *
 * "Отметить", not "Записать": what happens to a box is not what happens to a
 * number, and a preview whose rows all promise the same verb hides that a tick
 * lands on a shared day-map rather than in a new record of its own.
 */
export function checkCheckboxLabel(check: CheckOp): string {
  return `Отметить ${check.source_text}`;
}

/**
 * What an op's ids mean, in words the user recognises.
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

/**
 * Per-operation editable state in the preview: whether that op ships.
 *
 * Named for what it holds rather than for metrics, because both lists use it
 * and a tick is not a metric: `MetricState` on `checkStates` read as if a
 * `CheckOp` were a kind of `LogMetricOp`, which is exactly the confusion this
 * slice exists to prevent.
 */
export interface OpEnabledState {
  enabled: boolean;
}

/** The pair of ids any plan operation resolves by — all `resolveLabel` needs. */
export interface OpTarget {
  category_id: number;
  field_id: number;
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
  /** Refiles the plan under another day, minting a fresh idempotency key with it. */
  setEntryDate: (date: string) => void;
  draft: DraftState;
  applyState: ApplyState;
  /** One entry per metric of the current plan, index-aligned with it. */
  metricStates: OpEnabledState[];
  /** The boxes the retelling ticks. Never a full map: absence changes nothing. */
  checklist: CheckOp[];
  /** One entry per checklist op of the current plan, index-aligned with it. */
  checkStates: OpEnabledState[];
  /** What the model heard but could not place. Read-only: it creates nothing. */
  unresolved: DailySummaryPlan['unresolved'];
  /** How many operations — metrics and ticks together — would be written now. */
  enabledCount: number;
  /** The day's text as the backend resolved it, or null when there is none. */
  journal: JournalOp | null;
  /** Whether the day's text ships. On by default: appending loses nothing. */
  journalEnabled: boolean;
  setJournalEnabled: (enabled: boolean) => void;
  /** Whether the append is turned into a replacement. Off unless asked for. */
  journalReplace: boolean;
  setJournalReplace: (replace: boolean) => void;
  /** True when there is existing text a replacement could actually drop. */
  canReplaceJournal: boolean;
  /** Whether the apply would write anything — the apply button's guard. */
  canApply: boolean;
  /** False while the text is blank or a draft is already in flight. */
  canGenerate: boolean;
  /** Ask the LLM for a plan. A blank text is a no-op, not a request. */
  generate: () => Promise<void>;
  /** The category and field names behind an op's ids, ids as the fallback. */
  resolveLabel: (target: OpTarget) => MetricLabel;
  /** Check or uncheck one metric of the preview. */
  toggleMetric: (index: number, enabled: boolean) => void;
  /** Check or uncheck one checklist tick of the preview. */
  toggleCheck: (index: number, enabled: boolean) => void;
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
function initialMetricStates(plan: DailySummaryPlan): OpEnabledState[] {
  return plan.metrics.map((metric) => ({
    enabled: !metric.uncertain && !metric.implausible,
  }));
}

/**
 * The ticks of a plan, tolerating a response that carries none.
 *
 * `checklist` is optional on the wire so a frontend deployed ahead of its
 * backend reads an old draft as "no boxes" rather than crashing on the preview.
 */
function planChecklist(plan: DailySummaryPlan): CheckOp[] {
  return plan.checklist ?? [];
}

/** Default per tick: a confident one is opted in, a doubtful one costs a click. */
function initialCheckStates(plan: DailySummaryPlan): OpEnabledState[] {
  return planChecklist(plan).map((check) => ({ enabled: !check.uncertain }));
}

/** The apply payload: the metrics left checked, in plan order. */
function selectedMetrics(plan: DailySummaryPlan, states: OpEnabledState[]): LogMetricOp[] {
  return plan.metrics.filter((_, i) => states[i]?.enabled);
}

/** The apply payload: the ticks left checked, in plan order. */
function selectedChecks(plan: DailySummaryPlan, states: OpEnabledState[]): CheckOp[] {
  return planChecklist(plan).filter((_, i) => states[i]?.enabled);
}

/**
 * A key that identifies one attempt to write one day.
 *
 * Minted per plan, not per click: every click on "Записать" — including the
 * retry after a network timeout, where the write may well have landed — carries
 * the same key, which is exactly what lets the server recognise the second one
 * as a replay. A fresh draft is a new intent and gets a new key.
 */
function newApplyKey(): string {
  const uuid = globalThis.crypto?.randomUUID?.();
  return uuid ?? `day-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function useDailySummary({
  onApplied,
  today,
}: UseDailySummaryOptions): UseDailySummaryResult {
  const [transcript, setTranscript] = useState('');
  const [entryDate, setEntryDateState] = useState(today ?? todayISO());
  const [draft, setDraft] = useState<DraftState>({ status: 'idle' });
  const [metricStates, setMetricStates] = useState<OpEnabledState[]>([]);
  const [checkStates, setCheckStates] = useState<OpEnabledState[]>([]);
  const [applyState, setApplyState] = useState<ApplyState>({ status: 'idle' });
  const [categories, setCategories] = useState<Category[]>([]);
  const [journalEnabled, setJournalEnabled] = useState(true);
  const [journalReplace, setJournalReplace] = useState(false);
  const [applyKey, setApplyKey] = useState(newApplyKey);

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
    (target: OpTarget): MetricLabel => ({
      categoryName:
        namesById.categoryNames.get(target.category_id) ??
        unknownCategoryName(target.category_id),
      fieldName:
        namesById.fieldNames.get(`${target.category_id}:${target.field_id}`) ??
        unknownFieldName(target.field_id),
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
      setCheckStates(initialCheckStates(plan));
      // A new plan is a new day-writing intent: it must not inherit the key of
      // the previous one, or the server would answer the fresh plan with the
      // stale plan's result. Replacement goes back off with it — it is a choice
      // about a text that no longer exists.
      setApplyKey(newApplyKey());
      setJournalEnabled(true);
      setJournalReplace(false);
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

  /**
   * Move the plan to another day, under a key of its own.
   *
   * A key belongs to one day: reusing it for the next one would ask the server
   * to write a day it has already written under that key. The server rejects
   * that with a 409 and must keep doing so — this is the second line, which
   * turns a rejection the user would have to decipher into a normal apply.
   */
  const setEntryDate = useCallback(
    (date: string) => {
      if (date === entryDate) return;
      setEntryDateState(date);
      setApplyKey(newApplyKey());
    },
    [entryDate]
  );

  const toggleMetric = useCallback((index: number, enabled: boolean) => {
    setMetricStates((prev) => prev.map((s, i) => (i === index ? { enabled } : s)));
  }, []);

  const toggleCheck = useCallback((index: number, enabled: boolean) => {
    setCheckStates((prev) => prev.map((s, i) => (i === index ? { enabled } : s)));
  }, []);

  const journal = draft.status === 'done' ? (draft.plan.journal ?? null) : null;
  const canReplaceJournal = journal !== null && journal.existing_entry_id !== null;

  /**
   * The journal operation as it would be sent, or null when it is switched off.
   *
   * Replacement is applied here rather than stored in state so an operation can
   * never carry `replace` without the checkbox being on: the mode is derived
   * from the toggle every time, and a toggle the day cannot honour (no existing
   * text) changes nothing.
   */
  const journalToSend = useMemo<JournalOp | null>(() => {
    if (journal === null || !journalEnabled) return null;
    if (journalReplace && canReplaceJournal) return { ...journal, mode: 'replace' };
    return journal;
  }, [journal, journalEnabled, journalReplace, canReplaceJournal]);

  // One count for both lists: the button says how many things the click writes,
  // and a user reading "Записать выбранное (2)" does not care that one of them
  // is a number and the other a tick.
  const enabledCount =
    metricStates.filter((s) => s.enabled).length +
    checkStates.filter((s) => s.enabled).length;
  const canApply = enabledCount > 0 || journalToSend !== null;

  const apply = useCallback(async () => {
    if (draft.status !== 'done') return;
    const metrics = selectedMetrics(draft.plan, metricStates);
    const checklist = selectedChecks(draft.plan, checkStates);
    if (metrics.length === 0 && checklist.length === 0 && journalToSend === null) return;
    setApplyState({ status: 'applying' });
    try {
      await dailySummaryAPI.apply(
        entryDate,
        metrics,
        checklist,
        journalToSend,
        applyKey
      );
      onApplied();
    } catch (err) {
      // Plan and text both survive: the apply is all-or-nothing server-side, so
      // the same screen can be resubmitted as-is once the cause is fixed.
      setApplyState({
        status: 'error',
        message: err instanceof Error ? err.message : APPLY_ERROR,
      });
    }
  }, [draft, metricStates, checkStates, entryDate, journalToSend, applyKey, onApplied]);

  return {
    transcript,
    setTranscript,
    entryDate,
    setEntryDate,
    draft,
    applyState,
    metricStates,
    checklist: draft.status === 'done' ? planChecklist(draft.plan) : [],
    checkStates,
    unresolved: draft.status === 'done' ? draft.plan.unresolved : [],
    enabledCount,
    journal,
    journalEnabled,
    setJournalEnabled,
    journalReplace,
    setJournalReplace,
    canReplaceJournal,
    canApply,
    canGenerate: transcript.trim().length > 0 && draft.status !== 'loading',
    generate,
    resolveLabel,
    toggleMetric,
    toggleCheck,
    apply,
  };
}
