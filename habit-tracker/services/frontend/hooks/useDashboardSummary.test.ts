// [review:need-review] #302
// summary: tests for useDashboardSummary - first read, a period switch that keeps the old numbers until the new ones come, an answer that arrives out of order, an error with a retry, and a lost re-read that keeps the numbers

import { afterEach, describe, expect, it } from 'bun:test';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { APIError, type DashboardPeriod, type DashboardSummary } from '@/lib/api';
import { fullSummary } from '@/test-fixtures/dashboard-summary';
import { useDashboardSummary } from './useDashboardSummary';

afterEach(() => {
  cleanup();
});

interface Pending {
  period: DashboardPeriod;
  resolve: (summary: DashboardSummary) => void;
  reject: (error: unknown) => void;
}

/** A source that answers only when the test says so, so the order of arrival is the test's choice. */
function manualSource() {
  const pending: Pending[] = [];
  const source = (period: DashboardPeriod) =>
    new Promise<DashboardSummary>((resolve, reject) => {
      pending.push({ period, resolve, reject });
    });
  return { source, pending };
}

describe('useDashboardSummary', () => {
  it('starts on the week and reads it once', async () => {
    const asked: DashboardPeriod[] = [];
    const source = async (period: DashboardPeriod) => {
      asked.push(period);
      return fullSummary(period);
    };
    const { result } = renderHook(() => useDashboardSummary(source));

    expect(result.current.state.status).toBe('loading');
    await waitFor(() => expect(result.current.state.status).toBe('ready'));
    expect(asked).toEqual(['week']);
    expect(result.current.period).toBe('week');
  });

  it('keeps the old numbers on screen while the other period loads', async () => {
    const { source, pending } = manualSource();
    const { result } = renderHook(() => useDashboardSummary(source));
    await waitFor(() => expect(pending.length).toBe(1));
    act(() => pending[0].resolve(fullSummary('week')));
    await waitFor(() => expect(result.current.state.status).toBe('ready'));

    act(() => result.current.setPeriod('month'));
    await waitFor(() => expect(pending.length).toBe(2));
    expect(pending[1].period).toBe('month');
    const during = result.current.state;
    expect(during.status === 'ready' && during.refreshing).toBe(true);
    expect(during.status === 'ready' && during.summary.period).toBe('week');

    act(() => pending[1].resolve(fullSummary('month')));
    await waitFor(() => {
      const state = result.current.state;
      expect(state.status === 'ready' && state.summary.period === 'month' && !state.refreshing).toBe(
        true
      );
    });
  });

  it('ignores a slow answer for the period that was left', async () => {
    const { source, pending } = manualSource();
    const { result } = renderHook(() => useDashboardSummary(source));
    await waitFor(() => expect(pending.length).toBe(1));

    act(() => result.current.setPeriod('month'));
    await waitFor(() => expect(pending.length).toBe(2));

    // The month answers first; the week, launched earlier, arrives last.
    act(() => pending[1].resolve(fullSummary('month')));
    await waitFor(() => expect(result.current.state.status).toBe('ready'));
    act(() => pending[0].resolve(fullSummary('week')));
    await act(async () => {});

    const state = result.current.state;
    expect(state.status === 'ready' && state.summary.period).toBe('month');
  });

  it('ignores a failure of the period that was left', async () => {
    const { source, pending } = manualSource();
    const { result } = renderHook(() => useDashboardSummary(source));
    await waitFor(() => expect(pending.length).toBe(1));
    act(() => result.current.setPeriod('month'));
    await waitFor(() => expect(pending.length).toBe(2));

    act(() => pending[0].reject(new APIError(500, 'boom')));
    await act(async () => {});
    expect(result.current.state.status).toBe('loading');

    act(() => pending[1].resolve(fullSummary('month')));
    await waitFor(() => expect(result.current.state.status).toBe('ready'));
  });

  it('shows a Russian error and recovers on retry', async () => {
    const { source, pending } = manualSource();
    const { result } = renderHook(() => useDashboardSummary(source));
    await waitFor(() => expect(pending.length).toBe(1));

    act(() => pending[0].reject(new APIError(500, 'An error occurred')));
    await waitFor(() => expect(result.current.state.status).toBe('error'));
    const failed = result.current.state;
    expect(failed.status === 'error' && failed.message).toContain('Сервер');

    act(() => result.current.reload());
    expect(result.current.state.status).toBe('loading');
    await waitFor(() => expect(pending.length).toBe(2));
    act(() => pending[1].resolve(fullSummary('week')));
    await waitFor(() => expect(result.current.state.status).toBe('ready'));
  });

  it('does not show the week error over the month that is loading', async () => {
    const { source, pending } = manualSource();
    const { result } = renderHook(() => useDashboardSummary(source));
    await waitFor(() => expect(pending.length).toBe(1));
    act(() => pending[0].reject(new TypeError('Failed to fetch')));
    await waitFor(() => expect(result.current.state.status).toBe('error'));

    act(() => result.current.setPeriod('month'));
    expect(result.current.state.status).toBe('loading');
  });

  it('re-reads when the tab comes back and clears the failure flag on a good answer', async () => {
    const { source, pending } = manualSource();
    const { result } = renderHook(() => useDashboardSummary(source));
    await waitFor(() => expect(pending.length).toBe(1));
    act(() => pending[0].resolve(fullSummary('week')));
    await waitFor(() => expect(result.current.state.status).toBe('ready'));

    act(() => {
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await waitFor(() => expect(pending.length).toBe(2));
    expect(pending[1].period).toBe('week');
    act(() => pending[1].reject(new TypeError('Failed to fetch')));
    await waitFor(() => {
      const state = result.current.state;
      expect(state.status === 'ready' && state.refreshFailed).toBe(true);
    });

    act(() => result.current.reload());
    await waitFor(() => expect(pending.length).toBe(3));
    act(() => pending[2].resolve(fullSummary('week')));
    await waitFor(() => {
      const state = result.current.state;
      expect(state.status === 'ready' && !state.refreshFailed).toBe(true);
    });
  });

  it('keeps the numbers when a re-read of the same period fails', async () => {
    const { source, pending } = manualSource();
    const { result } = renderHook(() => useDashboardSummary(source));
    await waitFor(() => expect(pending.length).toBe(1));
    act(() => pending[0].resolve(fullSummary('week')));
    await waitFor(() => expect(result.current.state.status).toBe('ready'));

    act(() => result.current.reload());
    await waitFor(() => expect(pending.length).toBe(2));
    act(() => pending[1].reject(new TypeError('Failed to fetch')));
    await act(async () => {});

    expect(result.current.state.status).toBe('ready');
  });
});
