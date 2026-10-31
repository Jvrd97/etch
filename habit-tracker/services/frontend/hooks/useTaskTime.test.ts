// [review:need-review] PHASE-03/166
// summary: tests of the task-time read — an answer for the asked date, a re-read when the done marks change, no answer for a failed first read, and never an answer for another day

import { afterEach, describe, expect, it } from 'bun:test';
import { cleanup, renderHook, waitFor } from '@testing-library/react';
import type { TaskTimeDay } from '@/lib/api';
import { useTaskTime, type TaskTimeSource } from './useTaskTime';

afterEach(() => {
  cleanup();
});

function body(date: string, minutes = 0, today = date): TaskTimeDay {
  return {
    date,
    today,
    tasks: [{ plan_item_id: 'a', title: 'A', minutes }],
    untasked_minutes: 0,
    other_linked_minutes: 0,
    long_untasked: [],
    done_without_traces: [],
    commits_checked: false,
    untasked_share: { window_days: 30, observed_days: 0, intervals: 0, untasked: 0, share: null },
  };
}

function source(read: TaskTimeSource['read'], refreshMs = 3_600_000): TaskTimeSource {
  return { read, refreshMs };
}

describe('useTaskTime', () => {
  it('returns the answer for the asked date', async () => {
    const src = source(async (date) => body(date, 30));
    const { result } = renderHook(() => useTaskTime('2026-10-31', '', src));
    await waitFor(() => expect(result.current?.tasks[0]?.minutes).toBe(30));
  });

  it('reads again when the marks key changes', async () => {
    const reads: string[] = [];
    const src = source(async (date) => {
      reads.push(date);
      return body(date);
    });
    const { rerender } = renderHook(({ key }) => useTaskTime('2026-10-31', key, src), {
      initialProps: { key: 'a' },
    });
    await waitFor(() => expect(reads.length).toBe(1));
    rerender({ key: 'a,b' });
    await waitFor(() => expect(reads.length).toBe(2));
  });

  it('gives nothing for a failed first read and nothing without a date', async () => {
    const failing = source(async () => {
      throw new Error('down');
    });
    const { result } = renderHook(() => useTaskTime('2026-10-31', '', failing));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(result.current).toBeNull();
    const idle = renderHook(() => useTaskTime(null, '', failing));
    expect(idle.result.current).toBeNull();
  });

  it('never returns the answer of another day', async () => {
    const src = source(async () => body('2026-10-30'));
    const { result } = renderHook(() => useTaskTime('2026-10-31', '', src));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(result.current).toBeNull();
  });

  it('does not read again while a mark is being written, only once after', async () => {
    const reads: string[] = [];
    const src = source(async (date) => {
      reads.push(date);
      return body(date);
    });
    const { rerender } = renderHook(({ key }) => useTaskTime('2026-10-31', key, src), {
      initialProps: { key: '' as string | null },
    });
    await waitFor(() => expect(reads.length).toBe(1));
    rerender({ key: null });
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(reads.length).toBe(1);
    rerender({ key: 'a' });
    await waitFor(() => expect(reads.length).toBe(2));
  });

  it('keeps polling on the server today and stops on a past day', async () => {
    let todayReads = 0;
    const live = source(async (date) => {
      todayReads += 1;
      return body(date, 0, date);
    }, 10);
    renderHook(() => useTaskTime('2026-10-31', '', live));
    await waitFor(() => expect(todayReads).toBeGreaterThan(2));

    let pastReads = 0;
    const past = source(async (date) => {
      pastReads += 1;
      return body(date, 0, '2026-11-02');
    }, 10);
    renderHook(() => useTaskTime('2026-10-31', '', past));
    await new Promise((resolve) => setTimeout(resolve, 80));
    expect(pastReads).toBe(1);
  });
});
