// [review:need-review] PHASE-01/174, #176, #76, #78
// summary: Dashboard renders current streaks, accepts recent activity state and shows the Trends block in both shells - fixed thirty days on desktop, a period selector on mobile
import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import type { TrendState } from '@/hooks/useDashboard';
import type { TrendPeriod } from '@/lib/trends';

const TREND_ROW = {
  categoryId: 4,
  categoryName: 'Pushups',
  icon: null,
  unit: 'reps',
  color: '#ff6b6b',
  average: 38.6,
  deltaPercent: 18,
  sparkline: [{ date: '2026-09-30', value: 38.6 }],
};

let trendState: TrendState = { status: 'ready', trends: [TREND_ROW] };
let trendPeriod: TrendPeriod = 30;
const setTrendPeriod = mock<(period: TrendPeriod) => void>(() => {});

mock.module('@/hooks/useDashboard', () => ({
  INSIGHT_PERIOD_OPTIONS: [7, 30],
  useDashboard: () => ({
    stats: { categoriesCount: 0, entriesCount: 0, journalCount: 0 },
    hero: {
      ringProgress: 0,
      entriesToday: 0,
      lastEntry: null,
      tip: { text: 'Start here', kind: 'empty' },
    },
    avoidStreaks: [],
    categories: [],
    continueEntries: [],
    recentActivity: [],
    trendState,
    trendPeriod,
    loading: false,
    error: null,
    insight: { status: 'idle' },
    insightPeriod: 7,
    setError: () => {},
    setInsightPeriod: () => {},
    setTrendPeriod,
    generateInsight: async () => {},
  }),
}));

const { default: Dashboard } = await import('./page');
const { default: MobileDashboard } = await import('../m/dashboard/page');

afterEach(() => {
  cleanup();
  trendState = { status: 'ready', trends: [TREND_ROW] };
  trendPeriod = 30;
  setTrendPeriod.mockClear();
});

describe('Dashboard', () => {
  it('keeps Current streaks inside the hero card', () => {
    render(<Dashboard />);

    const hero = screen.getByTestId('dashboard-hero');
    expect(within(hero).getByRole('heading', { name: 'Current streaks' })).toBeTruthy();
  });

  it('keeps Current streaks inside the mobile hero card', () => {
    render(<MobileDashboard />);

    const hero = screen.getByTestId('mobile-dashboard-hero');
    expect(within(hero).getByRole('heading', { name: 'Current streaks' })).toBeTruthy();
  });

  it('shows the Trends block on desktop with its fixed thirty days and no selector', () => {
    render(<Dashboard />);

    const trends = screen.getByRole('region', { name: 'Trends' });
    expect(within(trends).getByRole('link', { name: /Pushups/ }).getAttribute('href')).toBe(
      '/categories/4'
    );
    expect(within(trends).queryByRole('group', { name: 'Trends period' })).toBeNull();
  });

  it('shows the Trends block on mobile and passes the chosen period to the hook', () => {
    trendPeriod = 7;
    render(<MobileDashboard />);

    const trends = screen.getByRole('region', { name: 'Trends' });
    expect(within(trends).getByRole('link', { name: /Pushups/ }).getAttribute('href')).toBe(
      '/m/categories/4?period=7'
    );
    fireEvent.click(within(trends).getByRole('button', { name: '90 days' }));
    expect(setTrendPeriod).toHaveBeenCalledWith(90);
  });

  it('keeps the dashboard readable when only the trends failed', () => {
    trendState = { status: 'error', message: 'table is down' };
    render(<Dashboard />);

    expect(screen.getByRole('alert').textContent).toBe('table is down');
    expect(screen.getByTestId('dashboard-hero')).toBeTruthy();
  });
});
