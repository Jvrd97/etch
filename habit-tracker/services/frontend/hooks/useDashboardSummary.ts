'use client';
// [review:need-review] #302, #311
// summary: reads the dashboard summary for the chosen period - the latest request launched wins, so a slow answer for the old period never overwrites the new one; a period switch keeps the old numbers on screen (`refreshing`) until the new ones arrive; the day comes from the answer itself (`today`), and returning to the tab re-reads it
// summary: #311 round 2 — a quick A→B→C switch keeps the numbers last on screen
// summary: #311 — each period is kept in the shared read cache: a re-visit, or a return to a period already seen, draws its numbers at once and re-reads them behind the screen

import { useCallback, useState } from 'react';
// A namespace import read at call time, as in `useClaudeUsage`: suites that mock
// `@/lib/api` with a fixed list of names must still link every screen.
import * as api from '@/lib/api';
import type { DashboardPeriod, DashboardSummary } from '@/lib/api';
import { DEFAULT_DASHBOARD_PERIOD, dashboardErrorMessage } from '@/lib/dashboard-summary';
import { useQuery, useQueryData, type QueryState } from '@/lib/query-cache';

export type DashboardSummaryState =
  | { status: 'loading' }
  /** `refreshing`: the other period is on its way; `refreshFailed`: the last re-read of this period was lost and these numbers are the earlier ones. */
  | { status: 'ready'; summary: DashboardSummary; refreshing: boolean; refreshFailed: boolean }
  | { status: 'error'; message: string };

/** The read, as a parameter so tests need no module mock. Keep the function stable between renders. */
export type DashboardSummarySource = (period: DashboardPeriod) => Promise<DashboardSummary>;

const API_SOURCE: DashboardSummarySource = (period) => api.dashboardAPI.summary(period);

export interface DashboardSummaryHandle {
  state: DashboardSummaryState;
  period: DashboardPeriod;
  setPeriod: (period: DashboardPeriod) => void;
  /** Ask again for the period on screen; the way out of an error. */
  reload: () => void;
}

/** The cache key of one period's summary. */
export function dashboardKey(period: DashboardPeriod): string {
  return `dashboard:${period}`;
}

export function useDashboardSummary(
  source: DashboardSummarySource = API_SOURCE
): DashboardSummaryHandle {
  const [period, setPeriodState] = useState<DashboardPeriod>(DEFAULT_DASHBOARD_PERIOD);
  // The period on screen before the switch: its numbers stay while the new one loads.
  const [left, setLeft] = useState<DashboardPeriod>(DEFAULT_DASHBOARD_PERIOD);
  const { state, refresh } = useQuery(dashboardKey(period), () => source(period), {
    refreshOnVisible: true,
  });
  const leftSummary = useQueryData<DashboardSummary>(dashboardKey(left));

  // The period whose numbers are on screen: the current one once it has them,
  // otherwise the one left before — so A→B→C keeps A's numbers, not a spinner.
  const shown = state.status === 'ready' ? period : left;
  const setPeriod = useCallback(
    (next: DashboardPeriod) => {
      setLeft(shown);
      setPeriodState(next);
    },
    [shown]
  );

  /** Ask again for the period on screen; a retry from an error shows the wait again. */
  const reload = useCallback(() => {
    void refresh();
  }, [refresh]);

  return { state: deriveState(state, leftSummary), period, setPeriod, reload };
}

function deriveState(
  state: QueryState<DashboardSummary>,
  leftSummary: DashboardSummary | undefined
): DashboardSummaryState {
  if (state.status === 'ready') {
    return {
      status: 'ready',
      summary: state.data,
      refreshing: false,
      refreshFailed: state.error !== null && !state.refreshing,
    };
  }
  if (state.status === 'error') return { status: 'error', message: dashboardErrorMessage(state.error) };
  if (leftSummary !== undefined) {
    return { status: 'ready', summary: leftSummary, refreshing: true, refreshFailed: false };
  }
  return { status: 'loading' };
}
