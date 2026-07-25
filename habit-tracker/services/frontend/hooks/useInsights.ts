'use client';
// [review:need-review] PHASE-01/46-mobile-insights
// summary: Insights-screen state extracted from app/insights/page.tsx so the desktop page and /m/insights share the same report list, per-report open/close/load flow, reload and the run logic (period selection + generate) via the shared useInsightRun primitive; formatReportDate is the one date formatter both shells render

import { useCallback, useEffect, useState } from 'react';
import { insightsAPI, type AIReport, type AIReportListItem } from '@/lib/api';
import {
  INSIGHT_PERIOD_OPTIONS,
  useInsightRun,
  type InsightPeriod,
  type InsightRunState,
} from './useInsightRun';

// Re-exported so the Insights shell imports the period vocabulary and the hook
// from one place; the definitions live in useInsightRun.
export { INSIGHT_PERIOD_OPTIONS };
export type { InsightPeriod };

/**
 * The currently expanded report, if any.
 *
 * A single discriminated slot rather than parallel booleans: at most one report
 * is open, loading or errored at a time, so the id travels with the state and a
 * second report cannot silently claim the first one's spinner.
 */
export type ReportView =
  | { status: 'closed' }
  | { status: 'loading'; id: number }
  | { status: 'error'; id: number; message: string }
  | { status: 'open'; id: number; report: AIReport };

/** Everything an Insights screen needs; the two shells differ only in markup. */
export interface UseInsightsResult {
  reports: AIReportListItem[];
  loading: boolean;
  error: string | null;
  view: ReportView;
  /** Selected analysis window for the next разбор. */
  period: InsightPeriod;
  setPeriod: (period: InsightPeriod) => void;
  /** State of the run triggered by {@link UseInsightsResult.generate}. */
  runState: InsightRunState;
  setError: (message: string | null) => void;
  /** Expand a report, fetching its body; a second tap on the open one collapses it. */
  openReport: (id: number) => Promise<void>;
  /** Re-fetch the list, e.g. after a fresh analysis was generated. */
  reload: () => Promise<void>;
  /** Generate a разбор over {@link UseInsightsResult.period}, then open it. */
  generate: () => Promise<void>;
  /** Drop the run state back to idle — dismiss its error banner. */
  dismissRun: () => void;
}

export function useInsights(): UseInsightsResult {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reports, setReports] = useState<AIReportListItem[]>([]);
  const [view, setView] = useState<ReportView>({ status: 'closed' });

  const loadReports = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      setReports(await insightsAPI.getAll());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load reports');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadReports();
  }, [loadReports]);

  const openReport = useCallback(
    async (id: number) => {
      // A second tap on the already-open report collapses it rather than
      // re-fetching a body that is already on screen.
      if (view.status === 'open' && view.id === id) {
        setView({ status: 'closed' });
        return;
      }
      setView({ status: 'loading', id });
      try {
        const report = await insightsAPI.getById(id);
        setView({ status: 'open', id, report });
      } catch (err) {
        setView({
          status: 'error',
          id,
          message: err instanceof Error ? err.message : 'Failed to load report',
        });
      }
    },
    [view]
  );

  // A fresh разбор refreshes the list and drops the reader straight into the
  // report they just asked for; the run then returns to idle.
  const {
    period,
    setPeriod,
    state: runState,
    reset: dismissRun,
    generate,
  } = useInsightRun(async (report) => {
    await loadReports();
    await openReport(report.id);
  });

  return {
    reports,
    loading,
    error,
    view,
    period,
    setPeriod,
    runState,
    setError,
    openReport,
    reload: loadReports,
    generate,
    dismissRun,
  };
}

/** Localised, human-readable timestamp for a report's `created_at`. */
export function formatReportDate(iso: string): string {
  return new Date(iso).toLocaleString('ru-RU', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}
