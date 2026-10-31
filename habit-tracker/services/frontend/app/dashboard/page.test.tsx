// [review:need-review] #302
// summary: the two Dashboard pages read /dashboard/summary through the real api client and draw the summary - a stubbed fetch, no module mock, so the request path and period query are the ones the browser sends

import { afterEach, beforeEach, describe, expect, it } from 'bun:test';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { fullSummary } from '@/test-fixtures/dashboard-summary';
import type { DashboardPeriod } from '@/lib/api';

const realFetch = globalThis.fetch;
let requested: string[] = [];

beforeEach(() => {
  requested = [];
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = String(input);
    requested.push(url);
    const period: DashboardPeriod = url.endsWith('period=month') ? 'month' : 'week';
    return new Response(JSON.stringify(fullSummary(period)), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  }) as typeof fetch;
});

afterEach(() => {
  cleanup();
  globalThis.fetch = realFetch;
});

const { default: Dashboard } = await import('./page');
const { default: MobileDashboard } = await import('../m/dashboard/page');

describe('Dashboard pages', () => {
  it('desktop asks for the week and then the month', async () => {
    render(<Dashboard />);
    await waitFor(() => expect(screen.getByRole('region', { name: 'Серии' })).toBeTruthy());
    expect(requested).toEqual(['/api/v1/dashboard/summary?period=week']);

    fireEvent.click(screen.getByRole('button', { name: 'Месяц' }));
    await waitFor(() =>
      expect(screen.getByRole('region', { name: 'Лучшее за месяц' })).toBeTruthy()
    );
    expect(requested).toEqual([
      '/api/v1/dashboard/summary?period=week',
      '/api/v1/dashboard/summary?period=month',
    ]);
  });

  it('mobile draws the same summary', async () => {
    render(<MobileDashboard />);
    await waitFor(() => expect(screen.getByRole('region', { name: 'Инсайт недели' })).toBeTruthy());
    expect(requested).toEqual(['/api/v1/dashboard/summary?period=week']);
  });
});
