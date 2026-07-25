'use client';
// [review:need-review] PHASE-01/43-mobile-dashboard
// summary: Dashboard state extracted from app/page.tsx so the desktop page and /m share the same data load, KPI stats and AI-insight flow

import { useCallback, useEffect, useState } from 'react';
import { categoriesAPI, entriesAPI, journalAPI } from '@/lib/api';
import { computeDashboardStats, type DashboardStats } from '@/lib/dashboard-stats';
import {
  INSIGHT_PERIOD_OPTIONS,
  useInsightRun,
  type InsightPeriod,
  type InsightRunState,
} from './useInsightRun';

// Re-exported so screens keep importing the analysis-window vocabulary from the
// Dashboard hook they already depend on; the definitions live in useInsightRun.
export { INSIGHT_PERIOD_OPTIONS };
export type { InsightPeriod };

/** Discriminated state of the on-demand AI insight panel. */
export type InsightState = InsightRunState;

/** How many journal notes the dashboard total is computed from. */
const JOURNAL_TOTAL_LIMIT = 5;

/** Entries that fill the hero progress ring completely. */
const RING_TARGET_ENTRIES = 10;

/** Everything a Dashboard screen needs; the two shells differ only in markup. */
export interface UseDashboardResult {
  stats: DashboardStats;
  /** Fraction of the hero ring to fill, clamped to 0..1. */
  ringProgress: number;
  loading: boolean;
  error: string | null;
  insight: InsightState;
  insightPeriod: InsightPeriod;
  setError: (message: string | null) => void;
  setInsightPeriod: (period: InsightPeriod) => void;
  /** Kick off an AI analysis over the selected period. */
  generateInsight: () => Promise<void>;
}

const EMPTY_STATS: DashboardStats = {
  categoriesCount: 0,
  entriesCount: 0,
  journalCount: 0,
  recentEntries: [],
};

export function useDashboard(): UseDashboardResult {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState<DashboardStats>(EMPTY_STATS);

  // No onReady handler: the panel renders the fresh report inline, so the run
  // parks on `ready` rather than being consumed elsewhere.
  const {
    period: insightPeriod,
    setPeriod: setInsightPeriod,
    state: insight,
    generate: generateInsight,
  } = useInsightRun();

  const loadDashboardData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      // Fetch the full entries list (backend default limit) so the Entries KPI
      // reflects the real total; the recent-activity feed is sliced client-side.
      // journal.total is the backend total regardless of the fetch limit.
      const [categories, entries, journal] = await Promise.all([
        categoriesAPI.getAll(),
        entriesAPI.getAll(),
        journalAPI.getAll({ limit: JOURNAL_TOTAL_LIMIT }),
      ]);

      setStats(computeDashboardStats(categories.length, entries, journal.total));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load dashboard data');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadDashboardData();
  }, [loadDashboardData]);

  return {
    stats,
    ringProgress: Math.min(stats.entriesCount / RING_TARGET_ENTRIES, 1),
    loading,
    error,
    insight,
    insightPeriod,
    setError,
    setInsightPeriod,
    generateInsight,
  };
}
