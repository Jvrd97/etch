// [review:need-review] PHASE-01/46-mobile-insights
// summary: tests for useInsightRun — default period, period selection, loading→ready without a handler, loading→idle with onReady (handler receives the report), error surfacing and reset

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { act, cleanup, renderHook } from '@testing-library/react';
import type { AIReport } from '@/lib/api';

const REPORT: AIReport = {
  id: 42,
  period_days: 30,
  content: '# Разбор',
  model: 'test-model',
  created_at: '2026-07-24T00:00:00Z',
};

let createInsight: ReturnType<typeof mock>;

// The whole module is replaced process-wide, so members other suites reach for
// stay present even though this suite only exercises insightsAPI.create.
mock.module('@/lib/api', () => ({
  // The goal board's client (#93). Present in every api mock for the same
  // reason the rest of the surface is: bun fixes a module's export names on
  // first link, so a mock that omits it deletes it for whoever runs next.
  goalsAPI: {
    get: () => Promise.resolve(null),
    patchMilestone: () => Promise.resolve(null),
  },
  // The quick-mark directory and its one write path (#121). Present in every
  // api mock for the reason named above: bun fixes a module's export names on
  // first link, so a mock that omits an export deletes it for whoever links next.
  quickMarksAPI: {
    list: () => Promise.resolve([]),
    tap: () => Promise.resolve(null),
    undo: () => Promise.resolve(null),
    sources: () => Promise.resolve([]),
  },
  // The day screen's client (#86). Present in every api mock for the same
  // reason the rest of the surface is: bun fixes a module's export names on
  // first link, so a mock that omits it deletes it for whoever runs next.
  dayAPI: {
    getToday: () => Promise.resolve(null),
    get: () => Promise.resolve(null),
  },
  dailySummaryAPI: {
    draft: () => Promise.resolve({ metrics: [], unresolved: [] }),
    apply: () => Promise.resolve({ entry_ids: [] }),
  },
  onboardingAPI: { draft: () => Promise.resolve({ operations: [] }) },
  categoriesAPI: {
    getAll: () => Promise.resolve([]),
    getById: () => Promise.resolve(null),
    getStreak: () => Promise.resolve(null),
    create: () => Promise.resolve(null),
    update: () => Promise.resolve(null),
    delete: () => Promise.resolve(undefined),
  },
  entriesAPI: {
    getAll: () => Promise.resolve([]),
    create: () => Promise.resolve(null),
    update: () => Promise.resolve(null),
    delete: () => Promise.resolve(undefined),
  },
  journalAPI: {
    getAll: () => Promise.resolve({ items: [], total: 0 }),
    getById: () => Promise.resolve(null),
    create: () => Promise.resolve(null),
  },
  insightsAPI: {
    create: (period?: number) => createInsight(period),
    getAll: () => Promise.resolve([]),
    getById: () => Promise.resolve(REPORT),
  },
  tableAPI: { get: () => Promise.resolve({ days: [] }) },
}));

const { useInsightRun } = await import('./useInsightRun');

beforeEach(() => {
  createInsight = mock(() => Promise.resolve(REPORT));
});

afterEach(() => {
  cleanup();
});

describe('useInsightRun', () => {
  it('starts idle on the default 30-day window', () => {
    const { result } = renderHook(() => useInsightRun());

    expect(result.current.state).toEqual({ status: 'idle' });
    expect(result.current.period).toBe(30);
  });

  it('generates over the selected period and lands in ready without a handler', async () => {
    const { result } = renderHook(() => useInsightRun());

    act(() => {
      result.current.setPeriod(7);
    });
    await act(async () => {
      await result.current.generate();
    });

    expect(createInsight).toHaveBeenLastCalledWith(7);
    expect(result.current.state).toEqual({ status: 'ready', report: REPORT });
  });

  it('hands the fresh report to onReady and returns to idle', async () => {
    const received: AIReport[] = [];
    const onReady = mock((report: AIReport): Promise<void> => {
      received.push(report);
      return Promise.resolve();
    });
    const { result } = renderHook(() => useInsightRun(onReady));

    await act(async () => {
      await result.current.generate();
    });

    expect(onReady).toHaveBeenCalledTimes(1);
    expect(received[0]).toEqual(REPORT);
    // With a handler the run does not park on `ready` — the handler owns what
    // happens next (reload + open), so the button goes back to idle.
    expect(result.current.state).toEqual({ status: 'idle' });
  });

  it('surfaces a create failure and reset clears it', async () => {
    createInsight = mock(() => Promise.reject(new Error('llm down')));
    const { result } = renderHook(() => useInsightRun());

    await act(async () => {
      await result.current.generate();
    });
    expect(result.current.state).toEqual({ status: 'error', message: 'llm down' });

    act(() => {
      result.current.reset();
    });
    expect(result.current.state).toEqual({ status: 'idle' });
  });
});
