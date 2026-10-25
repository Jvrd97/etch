// [review:need-review] PHASE-03/164
// summary: tests for useAgentStatus — the status is read once on mount, a failed read leaves the banner out rather than breaking the day screen, and the read is repeated on the refresh interval

import { afterEach, describe, expect, it } from 'bun:test';
import { cleanup, renderHook, waitFor } from '@testing-library/react';
import type { AgentStatus } from '@/lib/api';
import { useAgentStatus } from './useAgentStatus';

afterEach(() => {
  cleanup();
});

const STATUS: AgentStatus = { agents: [], silence_threshold_seconds: 1800, today: '2026-10-25' };

describe('useAgentStatus', () => {
  it('reads the status once on mount', async () => {
    let calls = 0;
    const source = {
      read: async () => {
        calls += 1;
        return STATUS;
      },
      refreshMs: 60_000,
    };
    const { result } = renderHook(() => useAgentStatus(source));

    await waitFor(() => expect(result.current).toEqual(STATUS));
    expect(calls).toBe(1);
  });

  it('is null when the read fails, and does not throw', async () => {
    const source = {
      read: async (): Promise<AgentStatus> => {
        throw new Error('offline');
      },
      refreshMs: 60_000,
    };
    const { result } = renderHook(() => useAgentStatus(source));

    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(result.current).toBeNull();
  });

  it('reads again on the interval and keeps the last answer when a read fails', async () => {
    const answers: Array<AgentStatus | Error> = [STATUS, new Error('offline')];
    let calls = 0;
    const source = {
      read: async () => {
        calls += 1;
        const answer = answers.shift();
        if (answer instanceof Error || answer === undefined) throw new Error('offline');
        return answer;
      },
      refreshMs: 10,
    };
    const { result } = renderHook(() => useAgentStatus(source));

    await waitFor(() => expect(calls).toBeGreaterThanOrEqual(2));
    expect(result.current).toEqual(STATUS);
  });
});
