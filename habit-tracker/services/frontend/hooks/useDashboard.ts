'use client';
// [review:need-review] PHASE-01/73-dashboard-hero-today-ring, PHASE-01/174, #176, #76, #78
// summary: Dashboard state exposes loaded categories, Continue tracking, the merged recent-activity feed and the Trends block, which loads its own GET /table per period and fails on its own

import { useCallback, useEffect, useState } from 'react';
import {
  categoriesAPI,
  entriesAPI,
  journalAPI,
  tableAPI,
  type Category,
  type CategoryStreak,
  type Entry,
} from '@/lib/api';
import { previousDay } from '@/lib/chart-utils';
import {
  computeDashboardHero,
  computeDashboardStats,
  type DashboardHero,
  type DashboardStats,
} from '@/lib/dashboard-stats';
import { todayISO } from '@/lib/date';
import { mergeActivityFeed, type ActivityFeedItem } from '@/lib/activity-feed';
import { partitionTodayCategories } from '@/lib/today-categories';
import {
  DEFAULT_TREND_PERIOD,
  buildDashboardTrends,
  trendDateRange,
  type DashboardTrend,
  type TrendPeriod,
} from '@/lib/trends';
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

/**
 * Trends load apart from the rest of the dashboard: a slow or failed table
 * request must not hold the hero back, and a period change must not reload it.
 */
export type TrendState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; trends: DashboardTrend[] };

/** Answer for a user with nothing to trend; no request is made for it. */
const NO_TRENDS: TrendState = { status: 'ready', trends: [] };

export interface AvoidStreak {
  category: Category;
  streak: CategoryStreak;
}

/**
 * Ceiling on the two-day window fetch. Explicit, so the ring and `entriesToday`
 * count every entry of the day instead of silently inheriting whatever page
 * size the server defaults to.
 */
const DAY_WINDOW_LIMIT = 1000;

/**
 * Rows in the recent-activity feed. Each source is fetched with the same bound
 * before the merge, so the newest rows of the two together are always present.
 */
const RECENT_ACTIVITY_LIMIT = 5;

async function loadLatestCategoryEntry(categoryId: number): Promise<Entry[]> {
  return entriesAPI.getAll({
    categoryId,
    limit: 1,
    sort: 'created_at_desc',
  });
}

/** Everything a Dashboard screen needs; the two shells differ only in markup. */
export interface UseDashboardResult {
  stats: DashboardStats;
  /** Today's ring, the last thing written, and the tip of the day. */
  hero: DashboardHero;
  avoidStreaks: AvoidStreak[];
  categories: Category[];
  continueEntries: Entry[];
  recentActivity: ActivityFeedItem[];
  trendState: TrendState;
  trendPeriod: TrendPeriod;
  loading: boolean;
  error: string | null;
  insight: InsightState;
  insightPeriod: InsightPeriod;
  setError: (message: string | null) => void;
  setInsightPeriod: (period: InsightPeriod) => void;
  setTrendPeriod: (period: TrendPeriod) => void;
  /** Kick off an AI analysis over the selected period. */
  generateInsight: () => Promise<void>;
}

const EMPTY_STATS: DashboardStats = {
  categoriesCount: 0,
  entriesCount: 0,
  journalCount: 0,
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
  const [avoidStreaks, setAvoidStreaks] = useState<AvoidStreak[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [continueEntries, setContinueEntries] = useState<Entry[]>([]);
  const [recentActivity, setRecentActivity] = useState<ActivityFeedItem[]>([]);
  const [trendState, setTrendState] = useState<TrendState>({ status: 'loading' });
  const [trendPeriod, setTrendPeriodState] = useState<TrendPeriod>(DEFAULT_TREND_PERIOD);

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
      // The unbounded list is still needed for the exact Entries KPI. The
      // activity feed uses its own bounded created_at query below.
      const [
        categories,
        entries,
        recentEntries,
        dayWindow,
        lastWritten,
        journal,
        streaks,
      ] = await Promise.all([
        categoriesAPI.getAll(),
        entriesAPI.getAll(),
        entriesAPI.getAll({
          sort: 'created_at_desc',
          limit: RECENT_ACTIVITY_LIMIT,
        }),
        entriesAPI.getAll({ startDate: yesterday, endDate: today, limit: DAY_WINDOW_LIMIT }),
        entriesAPI.getAll({ sort: 'created_at_desc', limit: 1 }),
        // One page serves the total, the newest note's date and the feed.
        journalAPI.getAll({ limit: RECENT_ACTIVITY_LIMIT }),
        categoriesAPI.getStreaks('avoid'),
      ]);

      const categoriesById = new Map(categories.map((category) => [category.id, category]));
      setAvoidStreaks(
        streaks.flatMap((streak) => {
          const category = categoriesById.get(streak.category_id);
          return category !== undefined && category.is_active ? [{ category, streak }] : [];
        })
      );

      const groups = partitionTodayCategories(
        categories.filter((category) => category.is_active)
      );
      const continueCategoryIds = [
        ...groups.quickForm.map((item) => item.category.id),
        ...groups.checklist.map((category) => category.id),
        ...groups.avoid.map((item) => item.category.id),
      ];
      const latestCategoryEntries = await Promise.all(
        continueCategoryIds.map(loadLatestCategoryEntry)
      );

      setStats(computeDashboardStats(categories.length, entries, journal.total));
      setCategories(categories);
      setContinueEntries(latestCategoryEntries.flat());
      setRecentActivity(
        mergeActivityFeed(recentEntries, journal.items).slice(0, RECENT_ACTIVITY_LIMIT)
      );
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

  const noCategories = !loading && categories.length === 0;

  useEffect(() => {
    if (loading || noCategories) return;
    // The answer of a period the user has already left must not overwrite the
    // current one, so each run owns a flag its cleanup flips.
    let cancelled = false;
    const now = new Date();
    const { dateFrom, dateTo } = trendDateRange(trendPeriod, now);
    tableAPI.get(dateFrom, dateTo).then(
      (table) => {
        if (cancelled) return;
        setTrendState({
          status: 'ready',
          trends: buildDashboardTrends(categories, table.days, trendPeriod, now),
        });
      },
      (err: unknown) => {
        if (cancelled) return;
        setTrendState({
          status: 'error',
          message: err instanceof Error ? err.message : 'Failed to load trends',
        });
      }
    );
    return () => {
      cancelled = true;
    };
  }, [loading, noCategories, categories, trendPeriod]);

  const setTrendPeriod = useCallback(
    (period: TrendPeriod) => {
      // Re-picking the shown period starts no request, so it must not park the
      // block on "loading" with nothing coming to end it.
      if (period === trendPeriod) return;
      setTrendPeriodState(period);
      setTrendState({ status: 'loading' });
    },
    [trendPeriod]
  );

  return {
    stats,
    hero,
    avoidStreaks,
    categories,
    continueEntries,
    recentActivity,
    trendState: noCategories ? NO_TRENDS : trendState,
    trendPeriod,
    loading,
    error,
    insight,
    insightPeriod,
    setError,
    setInsightPeriod,
    setTrendPeriod,
    generateInsight,
  };
}
