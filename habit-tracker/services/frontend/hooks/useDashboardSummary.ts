'use client';
// [review:need-review] #302
// summary: reads the dashboard summary for the chosen period - the latest request launched wins, so a slow answer for the old period never overwrites the new one; a period switch keeps the old numbers on screen (`refreshing`) until the new ones arrive; the day comes from the answer itself (`today`), and returning to the tab re-reads it

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRefreshOnVisible } from '@/hooks/useRefreshOnVisible';
// A namespace import read at call time, as in `useClaudeUsage`: suites that mock
// `@/lib/api` with a fixed list of names must still link every screen.
import * as api from '@/lib/api';
import type { DashboardPeriod, DashboardSummary } from '@/lib/api';
import { DEFAULT_DASHBOARD_PERIOD, dashboardErrorMessage } from '@/lib/dashboard-summary';

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

/** What the last answer was and for which period; the state shown is derived from it. */
type Answer =
  | { kind: 'none' }
  | { kind: 'summary'; summary: DashboardSummary; refreshFailed: boolean }
  | { kind: 'error'; message: string; period: DashboardPeriod };

export function useDashboardSummary(
  source: DashboardSummarySource = API_SOURCE
): DashboardSummaryHandle {
  const [period, setPeriod] = useState<DashboardPeriod>(DEFAULT_DASHBOARD_PERIOD);
  const [answer, setAnswer] = useState<Answer>({ kind: 'none' });
  // Order of launch, not of arrival: only the newest request may write.
  const launched = useRef(0);

  const load = useCallback(
    (target: DashboardPeriod) => {
      launched.current += 1;
      const mine = launched.current;
      Promise.resolve()
        .then(() => source(target))
        .then(
          (summary) => {
            if (mine === launched.current) setAnswer({ kind: 'summary', summary, refreshFailed: false });
          },
          (error: unknown) => {
            if (mine !== launched.current) return;
            // A lost re-read of the period already on screen keeps its numbers and says so.
            setAnswer((previous) =>
              previous.kind === 'summary' && previous.summary.period === target
                ? { ...previous, refreshFailed: true }
                : { kind: 'error', message: dashboardErrorMessage(error), period: target }
            );
          }
        );
    },
    [source]
  );

  useEffect(() => {
    load(period);
    return () => {
      // A newer launch or the unmount retires the request still in flight.
      launched.current += 1;
    };
  }, [load, period]);

  const reload = useCallback(() => {
    // A retry from an error shows the wait again instead of the old message.
    setAnswer((previous) => (previous.kind === 'error' ? { kind: 'none' } : previous));
    load(period);
  }, [load, period]);
  useRefreshOnVisible(reload);

  return { state: deriveState(answer, period), period, setPeriod, reload };
}

function deriveState(answer: Answer, period: DashboardPeriod): DashboardSummaryState {
  if (answer.kind === 'summary') {
    return {
      status: 'ready',
      summary: answer.summary,
      refreshing: answer.summary.period !== period,
      refreshFailed: answer.refreshFailed,
    };
  }
  if (answer.kind === 'error' && answer.period === period) {
    return { status: 'error', message: answer.message };
  }
  return { status: 'loading' };
}
