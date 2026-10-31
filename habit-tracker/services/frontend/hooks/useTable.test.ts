// [review:need-review] PHASE-03/264
// summary: tests for useTable's date range — the fourteen days end on the day the server runs (GET /day-mode), and on the browser's own day only when the server cannot be asked

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, renderHook, waitFor } from '@testing-library/react';
// A namespace read at call time, as the hook reads it.
import * as api from '@/lib/api';
import type { DayMode } from '@/lib/api';
import { replaceMethod } from '@/test-fixtures/replace-method';
import { todayISO } from '@/lib/date';
import { useTable, DAYS_SHOWN } from './useTable';

// A day no browser clock in this run is on: any read of the browser's calendar shows in a request.
const SERVER_DAY = '2031-03-05';
const RANGE_START = '2031-02-20';

const restores: (() => void)[] = [];
let tableGet: ReturnType<typeof mock>;
let readDayMode: ReturnType<typeof mock>;

beforeEach(() => {
  tableGet = mock(() => Promise.resolve({ categories: [], days: [] }));
  readDayMode = mock(() => Promise.resolve({ date: SERVER_DAY } as DayMode));
  restores.push(
    replaceMethod(api.tableAPI, 'get', tableGet as typeof api.tableAPI.get),
    replaceMethod(api.categoriesAPI, 'getAll', mock(() => Promise.resolve([]))),
    replaceMethod(api.agentAPI, 'dayMode', ((...args: unknown[]) => readDayMode(...args)) as typeof api.agentAPI.dayMode)
  );
});

afterEach(() => {
  cleanup();
  for (const restore of restores.splice(0)) restore();
});

describe('useTable range', () => {
  it('spans the fourteen days that end on the server day', async () => {
    const { result } = renderHook(() => useTable());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(DAYS_SHOWN).toBe(14);
    expect(tableGet).toHaveBeenCalledTimes(1);
    expect(tableGet).toHaveBeenCalledWith(RANGE_START, SERVER_DAY);
  });

  it('ends on the browser day when the server cannot name its day', async () => {
    readDayMode = mock(() => Promise.reject(new Error('offline')));
    const { result } = renderHook(() => useTable());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(tableGet.mock.calls[0][1]).toBe(todayISO());
  });
});
