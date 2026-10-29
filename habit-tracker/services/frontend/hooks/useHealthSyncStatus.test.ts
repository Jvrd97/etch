// [review:need-review] PHASE-03/132
// summary: tests for useHealthSyncStatus — read once on mount, a failed read leaves the block out, a read that throws synchronously does too, and the read repeats on the refresh interval

import { afterEach, describe, expect, it } from 'bun:test';
import { cleanup, renderHook, waitFor } from '@testing-library/react';
import type { HealthSyncStatus } from '@/lib/api';
import { useHealthSyncStatus } from './useHealthSyncStatus';

afterEach(cleanup);

const STATUS: HealthSyncStatus = {
  last_runs: [],
  last_success_at: null,
  lag_hours: null,
  interrupted: false,
};

describe('useHealthSyncStatus', () => {
  it('reads the status once on mount', async () => {
    let calls = 0;
    const source = {
      read: async () => {
        calls += 1;
        return STATUS;
      },
      refreshMs: 60_000,
    };
    const { result } = renderHook(() => useHealthSyncStatus(source));

    await waitFor(() => expect(result.current).toEqual(STATUS));
    expect(calls).toBe(1);
  });

  it('stays null when the read fails or throws', async () => {
    const failing = { read: () => Promise.reject(new Error('down')), refreshMs: 60_000 };
    const throwing = {
      read: (): Promise<HealthSyncStatus> => {
        throw new TypeError('not a function');
      },
      refreshMs: 60_000,
    };
    const a = renderHook(() => useHealthSyncStatus(failing));
    const b = renderHook(() => useHealthSyncStatus(throwing));

    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(a.result.current).toBeNull();
    expect(b.result.current).toBeNull();
  });

  it('repeats the read on the refresh interval', async () => {
    let calls = 0;
    const source = {
      read: async () => {
        calls += 1;
        return STATUS;
      },
      refreshMs: 10,
    };
    renderHook(() => useHealthSyncStatus(source));

    await waitFor(() => expect(calls).toBeGreaterThanOrEqual(3));
  });
});
