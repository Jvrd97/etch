// [review:need-review] PHASE-01/174, #176, #76
// summary: Dashboard renders current streaks and accepts recent activity state
import { describe, expect, it, mock } from 'bun:test';
import { render, screen, within } from '@testing-library/react';

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
    loading: false,
    error: null,
    insight: { status: 'idle' },
    insightPeriod: 7,
    setError: () => {},
    setInsightPeriod: () => {},
    generateInsight: async () => {},
  }),
}));

const { default: Dashboard } = await import('./page');
const { default: MobileDashboard } = await import('../m/dashboard/page');

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
});
