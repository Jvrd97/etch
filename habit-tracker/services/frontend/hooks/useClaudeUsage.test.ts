// [review:need-review] PHASE-03/220
// summary: tests for useClaudeUsage — the day on screen is read, an answer for another day is never shown, only the server's today is re-read on the interval, and a failed read leaves the block out instead of breaking the day

import { afterEach, describe, expect, it } from 'bun:test';
import { cleanup, renderHook, waitFor } from '@testing-library/react';
import type { ClaudeUsageDay } from '@/lib/api';
import { useClaudeUsage } from './useClaudeUsage';

afterEach(() => {
  cleanup();
});

function usage(date: string, today: string, sessions = 2): ClaudeUsageDay {
  return {
    date,
    today,
    sessions,
    assistant_turns: 8,
    input_tokens: 800,
    output_tokens: 400,
    cache_read_tokens: 8000,
    cache_creation_tokens: 80,
    sessions_past_boundary: 0,
  };
}

describe('useClaudeUsage', () => {
  it('reads the day on screen once', async () => {
    const asked: string[] = [];
    const source = {
      read: async (date: string) => {
        asked.push(date);
        return usage(date, '2026-10-26');
      },
      refreshMs: 60_000,
    };
    const { result } = renderHook(() => useClaudeUsage('2026-10-26', source));

    await waitFor(() => expect(result.current?.sessions).toBe(2));
    expect(asked).toEqual(['2026-10-26']);
  });

  it('is null while the date is unknown and reads nothing', async () => {
    let calls = 0;
    const source = {
      read: async (date: string) => {
        calls += 1;
        return usage(date, date);
      },
      refreshMs: 10,
    };
    const { result } = renderHook(() => useClaudeUsage(null, source));

    await new Promise((resolve) => setTimeout(resolve, 40));
    expect(result.current).toBeNull();
    expect(calls).toBe(0);
  });

  it('never shows the answer for the previous day under the new one', async () => {
    const source = {
      read: async (date: string) => usage(date, '2026-10-26', date === '2026-10-25' ? 7 : 1),
      refreshMs: 60_000,
    };
    const { result, rerender } = renderHook(({ date }) => useClaudeUsage(date, source), {
      initialProps: { date: '2026-10-25' },
    });
    await waitFor(() => expect(result.current?.sessions).toBe(7));

    rerender({ date: '2026-10-26' });
    expect(result.current).toBeNull();
    await waitFor(() => expect(result.current?.sessions).toBe(1));
  });

  it('re-reads the server today on the interval and leaves a past day alone', async () => {
    const calls: Record<string, number> = { '2026-10-26': 0, '2026-10-25': 0 };
    const source = {
      read: async (date: string) => {
        calls[date] += 1;
        return usage(date, '2026-10-26');
      },
      refreshMs: 10,
    };
    renderHook(() => useClaudeUsage('2026-10-26', source));
    renderHook(() => useClaudeUsage('2026-10-25', source));

    await waitFor(() => expect(calls['2026-10-26']).toBeGreaterThanOrEqual(3));
    expect(calls['2026-10-25']).toBe(1);
  });

  it('is null when the read fails, and does not throw', async () => {
    const source = {
      read: async (): Promise<ClaudeUsageDay> => {
        throw new Error('offline');
      },
      refreshMs: 60_000,
    };
    const { result } = renderHook(() => useClaudeUsage('2026-10-26', source));

    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(result.current).toBeNull();
  });

  it('survives a source that throws before it returns a promise', async () => {
    const source = {
      read: (): Promise<ClaudeUsageDay> => {
        throw new Error('sync boom');
      },
      refreshMs: 60_000,
    };
    const { result } = renderHook(() => useClaudeUsage('2026-10-26', source));

    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(result.current).toBeNull();
  });
});
