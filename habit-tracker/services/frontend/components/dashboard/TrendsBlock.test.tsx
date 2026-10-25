// [review:need-review] #78
// summary: tests for the dashboard Trends block - rows with unit-aware average and signed delta, links into each shell's category page, the mobile-only period selector, and its loading / error / empty states

import { afterEach, describe, expect, it } from 'bun:test';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import type { DashboardTrend } from '@/lib/trends';
import { TrendsBlock } from './TrendsBlock';

afterEach(cleanup);

const COLOR = '#ff6b6b';

function trend(overrides: Partial<DashboardTrend> = {}): DashboardTrend {
  return {
    categoryId: 4,
    categoryName: 'Pushups',
    icon: '💪',
    unit: 'reps',
    color: COLOR,
    average: 38.64,
    deltaPercent: 18.2,
    sparkline: [
      { date: '2026-09-28', value: 30 },
      { date: '2026-09-29', value: null },
      { date: '2026-09-30', value: 45 },
    ],
    ...overrides,
  };
}

function ready(...trends: DashboardTrend[]) {
  return { status: 'ready' as const, trends };
}

describe('TrendsBlock rows', () => {
  it('names the category, its average with the unit and the signed delta', () => {
    render(<TrendsBlock state={ready(trend())} period={30} onPeriodChange={() => {}} />);

    const row = screen.getByRole('link', { name: /Pushups/ });
    expect(row.textContent).toContain('avg 38.6 reps');
    expect(row.textContent).toContain('+18 % vs prev 30d');
    expect(screen.getByRole('heading', { name: 'Trends' })).toBeTruthy();
  });

  it('reads as one phrase to a screen reader, not as glued words', () => {
    render(<TrendsBlock state={ready(trend())} period={30} onPeriodChange={() => {}} />);
    expect(screen.getByRole('link', { name: 'Pushups avg 38.6 reps +18 % vs prev 30d' })).toBeTruthy();
  });

  it('shows a bare number for a field without a unit', () => {
    render(<TrendsBlock state={ready(trend({ unit: null }))} period={30} onPeriodChange={() => {}} />);
    expect(screen.getByRole('link', { name: /Pushups/ }).textContent).toContain('avg 38.6');
    expect(screen.queryByText(/reps/)).toBeNull();
  });

  it('shows a dash in place of a delta that cannot be told', () => {
    render(
      <TrendsBlock state={ready(trend({ deltaPercent: null }))} period={7} onPeriodChange={() => {}} />
    );
    expect(screen.getByRole('link', { name: /Pushups/ }).textContent).toContain('— vs prev 7d');
  });

  it('shows a fall with its minus sign and a zero average as a number', () => {
    render(
      <TrendsBlock
        state={ready(trend({ average: 0, deltaPercent: -100 }))}
        period={30}
        onPeriodChange={() => {}}
      />
    );
    const row = screen.getByRole('link', { name: /Pushups/ });
    expect(row.textContent).toContain('avg 0 reps');
    expect(row.textContent).toContain('-100 % vs prev 30d');
  });

  it('falls back to a color dot when the category has no icon', () => {
    const { container } = render(
      <TrendsBlock state={ready(trend({ icon: null }))} period={30} onPeriodChange={() => {}} />
    );
    expect(screen.queryByText('💪')).toBeNull();
    expect(container.querySelector('[data-testid="trend-dot"]')).toBeTruthy();
  });

  it('draws the sparkline in the category color and keeps it out of the accessibility tree', () => {
    const { container } = render(
      <TrendsBlock state={ready(trend())} period={30} onPeriodChange={() => {}} />
    );
    const svg = container.querySelector('svg');
    expect(svg?.getAttribute('aria-hidden')).toBe('true');
    const strokes = Array.from(svg?.querySelectorAll('path') ?? []).map((path) =>
      path.getAttribute('stroke')
    );
    // The gap on the 29th splits the line into two single-day runs.
    expect(strokes).toEqual([COLOR, COLOR]);
  });

  it('renders as many rows as it is given', () => {
    render(
      <TrendsBlock
        state={ready(trend(), trend({ categoryId: 5, categoryName: 'Water' }))}
        period={30}
        onPeriodChange={() => {}}
      />
    );
    expect(within(screen.getByRole('list')).getAllByRole('listitem')).toHaveLength(2);
  });
});

describe('TrendsBlock links', () => {
  it('opens the desktop category page, which opens on thirty days by itself', () => {
    render(<TrendsBlock state={ready(trend())} period={30} onPeriodChange={() => {}} />);
    expect(screen.getByRole('link', { name: /Pushups/ }).getAttribute('href')).toBe('/categories/4');
  });

  it('opens the mobile category page on the period the block shows', () => {
    const { rerender } = render(
      <TrendsBlock state={ready(trend())} period={30} onPeriodChange={() => {}} mobile />
    );
    expect(screen.getByRole('link', { name: /Pushups/ }).getAttribute('href')).toBe(
      '/m/categories/4?period=30'
    );
    rerender(<TrendsBlock state={ready(trend())} period={7} onPeriodChange={() => {}} mobile />);
    expect(screen.getByRole('link', { name: /Pushups/ }).getAttribute('href')).toBe(
      '/m/categories/4?period=7'
    );
  });
});

describe('TrendsBlock period selector', () => {
  it('is offered on mobile only', () => {
    const { rerender } = render(
      <TrendsBlock state={ready(trend())} period={30} onPeriodChange={() => {}} mobile />
    );
    expect(screen.getByRole('group', { name: 'Trends period' })).toBeTruthy();
    rerender(<TrendsBlock state={ready(trend())} period={30} onPeriodChange={() => {}} />);
    expect(screen.queryByRole('group', { name: 'Trends period' })).toBeNull();
  });

  it('marks the shown period as pressed and reports another choice', () => {
    const chosen: number[] = [];
    render(
      <TrendsBlock
        state={ready(trend())}
        period={30}
        onPeriodChange={(period) => chosen.push(period)}
        mobile
      />
    );

    expect(screen.getByRole('button', { name: '30 days', pressed: true })).toBeTruthy();
    expect(screen.getByRole('button', { name: '7 days', pressed: false })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '90 days' }));
    expect(chosen).toEqual([90]);
  });

  it('keeps the selector while the new period loads, so it can be changed again', () => {
    render(<TrendsBlock state={{ status: 'loading' }} period={7} onPeriodChange={() => {}} mobile />);
    expect(screen.getByRole('button', { name: '7 days', pressed: true })).toBeTruthy();
  });

  it('tells the reader a row is tappable', () => {
    render(<TrendsBlock state={ready(trend())} period={30} onPeriodChange={() => {}} mobile />);
    expect(screen.getByText('Tap a habit for details')).toBeTruthy();
  });
});

describe('TrendsBlock states', () => {
  it('announces loading politely', () => {
    render(<TrendsBlock state={{ status: 'loading' }} period={30} onPeriodChange={() => {}} />);
    expect(screen.getByRole('status').textContent).toContain('Loading trends');
  });

  it('shows a failed load as an alert inside the block', () => {
    render(
      <TrendsBlock
        state={{ status: 'error', message: 'table is down' }}
        period={30}
        onPeriodChange={() => {}}
      />
    );
    expect(screen.getByRole('alert').textContent).toBe('table is down');
    expect(screen.getByRole('heading', { name: 'Trends' })).toBeTruthy();
  });

  it('says what is missing when no category has numbers in the period', () => {
    render(<TrendsBlock state={ready()} period={90} onPeriodChange={() => {}} />);
    expect(screen.getByText('No numeric entries in the last 90 days yet.')).toBeTruthy();
    expect(screen.queryByRole('list')).toBeNull();
  });
});
