// [review:need-review] PHASE-01/46-mobile-insights
// summary: tests for useInsights — initial list load, default period, generate() creates over the selected period then reloads the list and opens the fresh report, and a create failure surfaces on runState

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import type { AIReport, AIReportListItem } from '@/lib/api';

const REPORT: AIReport = {
  id: 7,
  period_days: 7,
  content: '# Разбор за 7 дней',
  model: 'test-model',
  created_at: '2026-07-24T00:00:00Z',
};

const LIST_ITEM: AIReportListItem = {
  id: 7,
  period_days: 7,
  model: 'test-model',
  created_at: '2026-07-24T00:00:00Z',
  preview: 'preview',
};

let createInsight: ReturnType<typeof mock>;
let getAllInsights: ReturnType<typeof mock>;
let getInsightById: ReturnType<typeof mock>;

// The whole module is replaced process-wide, so members other suites reach for
// stay present even though this suite only exercises insightsAPI.
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
    getAll: () => getAllInsights(),
    getById: (id: number) => getInsightById(id),
  },
  tableAPI: { get: () => Promise.resolve({ days: [] }) },
}));

const { useInsights } = await import('./useInsights');

beforeEach(() => {
  createInsight = mock(() => Promise.resolve(REPORT));
  getAllInsights = mock(() => Promise.resolve([] as AIReportListItem[]));
  getInsightById = mock(() => Promise.resolve(REPORT));
});

afterEach(() => {
  cleanup();
});

describe('useInsights', () => {
  it('loads the report list and offers the 30-day window by default', async () => {
    const { result } = renderHook(() => useInsights());

    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.period).toBe(30);
    expect(result.current.runState).toEqual({ status: 'idle' });
  });

  it('generates over the selected period, then reloads and opens the fresh report', async () => {
    const { result } = renderHook(() => useInsights());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      result.current.setPeriod(7);
    });

    // The reload after create returns the new report so the list is fresh.
    getAllInsights = mock(() => Promise.resolve([LIST_ITEM]));

    await act(async () => {
      await result.current.generate();
    });

    expect(createInsight).toHaveBeenLastCalledWith(7);
    expect(getInsightById).toHaveBeenCalledWith(REPORT.id);
    expect(result.current.reports).toEqual([LIST_ITEM]);
    expect(result.current.view).toEqual({ status: 'open', id: REPORT.id, report: REPORT });
    // The run itself returns to idle once the report is on screen.
    expect(result.current.runState).toEqual({ status: 'idle' });
  });

  it('surfaces a create failure on runState and dismissRun clears it', async () => {
    const { result } = renderHook(() => useInsights());
    await waitFor(() => expect(result.current.loading).toBe(false));

    createInsight = mock(() => Promise.reject(new Error('llm down')));
    await act(async () => {
      await result.current.generate();
    });
    expect(result.current.runState).toEqual({ status: 'error', message: 'llm down' });

    act(() => {
      result.current.dismissRun();
    });
    expect(result.current.runState).toEqual({ status: 'idle' });
  });
});
