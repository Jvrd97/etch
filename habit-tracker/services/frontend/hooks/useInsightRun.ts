'use client';
// [review:need-review] PHASE-01/46-mobile-insights
// summary: shared create-and-track primitive for the on-demand AI разбор — owns the analysis-window selection, the idle/loading/error/ready state machine and the insightsAPI.create call, so useDashboard and useInsights drive one implementation instead of two copies of the same run logic

import { useCallback, useEffect, useRef, useState } from 'react';
import { insightsAPI, type AIReport } from '@/lib/api';

/** Selectable analysis windows for the AI insight, in days. */
export const INSIGHT_PERIOD_OPTIONS = [7, 30, 90] as const;
export type InsightPeriod = (typeof INSIGHT_PERIOD_OPTIONS)[number];

/** Default analysis window offered when a screen first mounts. */
const DEFAULT_INSIGHT_PERIOD: InsightPeriod = 30;

/**
 * Discriminated state of one on-demand AI insight run.
 *
 * A single slot rather than parallel booleans: a run is either idle, in flight,
 * failed, or finished with a report, and the terminal `ready` carries the report
 * so a screen can render it inline without a second lookup.
 */
export type InsightRunState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; report: AIReport };

export interface UseInsightRunResult {
  /** Currently selected analysis window. */
  period: InsightPeriod;
  setPeriod: (period: InsightPeriod) => void;
  state: InsightRunState;
  /** Drop back to idle — dismiss an error banner or clear a finished run. */
  reset: () => void;
  /** Kick off an analysis over the selected period. */
  generate: () => Promise<void>;
}

/**
 * Owns the create-and-track lifecycle of an AI разбор.
 *
 * When `onReady` is given it consumes the fresh report (e.g. reload a list and
 * open it) and the run returns to idle; without it the run terminates in `ready`
 * so a screen can render the report inline. Both the Insights and Dashboard
 * shells hang off this one state machine instead of keeping private copies.
 */
export function useInsightRun(
  onReady?: (report: AIReport) => void | Promise<void>
): UseInsightRunResult {
  const [period, setPeriod] = useState<InsightPeriod>(DEFAULT_INSIGHT_PERIOD);
  const [state, setState] = useState<InsightRunState>({ status: 'idle' });

  // Track the latest handler in a ref so `generate` keeps a stable identity even
  // when the caller passes a fresh closure each render (openReport changes with
  // the currently expanded report). Written in an effect, not during render:
  // a ref must not be mutated while rendering.
  const onReadyRef = useRef(onReady);
  useEffect(() => {
    onReadyRef.current = onReady;
  });

  const generate = useCallback(async () => {
    setState({ status: 'loading' });
    try {
      const report = await insightsAPI.create(period);
      const handle = onReadyRef.current;
      if (handle) {
        await handle(report);
        setState({ status: 'idle' });
      } else {
        setState({ status: 'ready', report });
      }
    } catch (err) {
      setState({
        status: 'error',
        message: err instanceof Error ? err.message : 'Failed to generate insight',
      });
    }
  }, [period]);

  const reset = useCallback(() => setState({ status: 'idle' }), []);

  return { period, setPeriod, state, reset, generate };
}
