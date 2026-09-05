'use client';
// [review:need-review] PHASE-01/73-dashboard-hero-today-ring, #176
// summary: Dashboard state exposes loaded categories and entries for Continue tracking

import { useCallback, useEffect, useState } from 'react';
import { categoriesAPI, entriesAPI, journalAPI, type Category, type Entry } from '@/lib/api';
import { previousDay } from '@/lib/chart-utils';
import {
  computeDashboardHero,
  computeDashboardStats,
  type DashboardHero,
  type DashboardStats,
} from '@/lib/dashboard-stats';
import { todayISO } from '@/lib/date';
import { partitionTodayCategories } from '@/lib/today-categories';
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

/**
 * Ceiling on the two-day window fetch. Explicit, so the ring and `entriesToday`
 * count every entry of the day instead of silently inheriting whatever page
 * size the server defaults to.
 */
const DAY_WINDOW_LIMIT = 1000;
export const CONTINUE_HISTORY_PAGE_SIZE = 100;

async function loadCategoryHistory(categoryId: number): Promise<Entry[]> {
  const entries: Entry[] = [];
  for (let skip = 0; ; skip += CONTINUE_HISTORY_PAGE_SIZE) {
    const page = await entriesAPI.getAll({ categoryId, skip, limit: CONTINUE_HISTORY_PAGE_SIZE });
    entries.push(...page);
    if (page.length < CONTINUE_HISTORY_PAGE_SIZE) return entries;
  }
}

/** Everything a Dashboard screen needs; the two shells differ only in markup. */
export interface UseDashboardResult {
  stats: DashboardStats;
  /** Today's ring, the last thing written, and the tip of the day. */
  hero: DashboardHero;
  categories: Category[];
  continueEntries: Entry[];
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

/**
 * What the hero shows before the first load answers.
 *
 * Derived from the same function as the real thing, on empty inputs, so the
 * placeholder can never drift out of shape from what replaces it.
 */
const EMPTY_HERO: DashboardHero = computeDashboardHero({
  categories: [],
  todayEntries: [],
  loggedYesterday: false,
  lastEntry: null,
  lastJournalDate: null,
  now: new Date(0),
});

export function useDashboard(): UseDashboardResult {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState<DashboardStats>(EMPTY_STATS);
  const [hero, setHero] = useState<DashboardHero>(EMPTY_HERO);
  const [categories, setCategories] = useState<Category[]>([]);
  const [continueEntries, setContinueEntries] = useState<Entry[]>([]);

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

      // One moment for the whole load: the day boundary, the tip's hour and the
      // "logged N ago" line all have to agree, and reading the clock three
      // times can straddle midnight.
      const now = new Date();
      const today = todayISO(now);
      const yesterday = previousDay(today);

      // The hero asks two narrow questions instead of scanning the history:
      // the two-day window it counts today from (and reads yesterday off, to
      // know whether a run is at stake), and the single last-written record.
      // The unbounded list below still feeds the Entries KPI and the
      // recent-activity feed, which #76 replaces — the hero no longer reads it.
      const [categories, entries, dayWindow, lastWritten, journal] = await Promise.all([
        categoriesAPI.getAll(),
        entriesAPI.getAll(),
        entriesAPI.getAll({ startDate: yesterday, endDate: today, limit: DAY_WINDOW_LIMIT }),
        entriesAPI.getAll({ sort: 'created_at_desc', limit: 1 }),
        journalAPI.getAll({ limit: JOURNAL_TOTAL_LIMIT }),
      ]);

      const groups = partitionTodayCategories(
        categories.filter((category) => category.is_active)
      );
      const continueCategoryIds = [
        ...groups.quickForm.map((item) => item.category.id),
        ...groups.checklist.map((category) => category.id),
        ...groups.avoid.map((item) => item.category.id),
      ];
      const categoryHistories = await Promise.all(
        continueCategoryIds.map(loadCategoryHistory)
      );

      setStats(computeDashboardStats(categories.length, entries, journal.total));
      setCategories(categories);
      setContinueEntries(categoryHistories.flat());
      setHero(
        computeDashboardHero({
          categories,
          todayEntries: dayWindow.filter((entry) => entry.entry_date === today),
          loggedYesterday: dayWindow.some((entry) => entry.entry_date === yesterday),
          lastEntry: lastWritten[0] ?? null,
          // Journal notes come back newest first, so the first item dates the
          // most recent note the user wrote.
          lastJournalDate: journal.items[0]?.entry_date ?? null,
          now,
        })
      );
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
    hero,
    categories,
    continueEntries,
    loading,
    error,
    insight,
    insightPeriod,
    setError,
    setInsightPeriod,
    generateInsight,
  };
}
