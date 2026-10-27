// [review:need-review] PHASE-03/228
// summary: tests for useDayMode — the server's current day is read on mount and every write goes to the date of that answer (never a browser date), a decision is replaced by the server's answer, a reset takes the day back to the schedule, a failed write keeps the last mode and says so, a failed read (also a client that throws before returning a promise) is reported and can be retried, and a tab that comes back after the day boundary reads the new day and writes to it

import { afterEach, describe, expect, it } from 'bun:test';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import type { DayMode } from '@/lib/api';
import { useDayMode, type DayModeClient } from './useDayMode';

afterEach(() => {
  cleanup();
});

const DATE = '2026-10-27';
const SCHEDULED: DayMode = { date: DATE, kind: 'work', nocode: true, source: 'schedule' };

function client(overrides: Partial<DayModeClient> = {}): DayModeClient {
  return {
    read: async () => SCHEDULED,
    set: async (_date, draft) => ({ date: DATE, ...draft, source: 'manual' }),
    clear: async () => SCHEDULED,
    ...overrides,
  };
}

describe('useDayMode', () => {
  it('reads the mode of the server day on mount', async () => {
    const { result } = renderHook(() => useDayMode(client()));

    await waitFor(() => expect(result.current.mode).toEqual(SCHEDULED));
  });

  it('takes the server answer of a decision, with both fields sent', async () => {
    const sent: unknown[] = [];
    const api = client({
      set: async (_date, draft) => {
        sent.push(draft);
        return { date: DATE, kind: draft.kind, nocode: draft.nocode, source: 'manual' };
      },
    });
    const { result } = renderHook(() => useDayMode(api));
    await waitFor(() => expect(result.current.mode).not.toBeNull());

    await act(async () => {
      await result.current.decide('vacation', true);
    });

    expect(sent).toEqual([{ kind: 'vacation', nocode: true }]);
    expect(result.current.mode?.source).toBe('manual');
    expect(result.current.mode?.kind).toBe('vacation');
  });

  it('goes back to the schedule on reset', async () => {
    const api = client({
      read: async () => ({ ...SCHEDULED, kind: 'sick', source: 'manual' }),
    });
    const { result } = renderHook(() => useDayMode(api));
    await waitFor(() => expect(result.current.mode?.source).toBe('manual'));

    await act(async () => {
      await result.current.reset();
    });

    expect(result.current.mode).toEqual(SCHEDULED);
  });

  it('keeps the last mode and reports a failed write', async () => {
    const api = client({
      set: async () => {
        throw new Error('offline');
      },
    });
    const { result } = renderHook(() => useDayMode(api));
    await waitFor(() => expect(result.current.mode).not.toBeNull());

    await act(async () => {
      await result.current.decide('dayoff', false);
    });

    expect(result.current.mode).toEqual(SCHEDULED);
    expect(result.current.error).not.toBeNull();
  });

  it('writes to the date the server named, not to a date of its own', async () => {
    const serverDay = '2026-10-26';
    const calls: string[] = [];
    const api = client({
      read: async () => ({ ...SCHEDULED, date: serverDay }),
      set: async (date, draft) => {
        calls.push(`set ${date}`);
        return { date, ...draft, source: 'manual' };
      },
      clear: async (date) => {
        calls.push(`clear ${date}`);
        return { ...SCHEDULED, date };
      },
    });
    const { result } = renderHook(() => useDayMode(api));
    await waitFor(() => expect(result.current.mode?.date).toBe(serverDay));

    await act(async () => {
      await result.current.decide('sick', false);
    });
    await act(async () => {
      await result.current.reset();
    });

    expect(calls).toEqual([`set ${serverDay}`, `clear ${serverDay}`]);
  });

  it('reports a failed read and recovers on retry', async () => {
    let attempts = 0;
    const api = client({
      read: async () => {
        attempts += 1;
        if (attempts === 1) throw new Error('offline');
        return SCHEDULED;
      },
    });
    const { result } = renderHook(() => useDayMode(api));

    await waitFor(() => expect(result.current.loadFailed).toBe(true));
    expect(result.current.mode).toBeNull();

    await act(async () => {
      await result.current.reload();
    });

    expect(result.current.loadFailed).toBe(false);
    expect(result.current.mode).toEqual(SCHEDULED);
  });

  it('reports a read whose client throws before it returns a promise', async () => {
    const api = client({
      read: () => {
        throw new TypeError('agentAPI.dayMode is not a function');
      },
    });
    const { result } = renderHook(() => useDayMode(api));

    await waitFor(() => expect(result.current.loadFailed).toBe(true));
    expect(result.current.mode).toBeNull();
  });

  it('reads the server day again when the tab becomes visible, and writes to the new date', async () => {
    let serverDay = '2026-10-26';
    const calls: string[] = [];
    const api = client({
      read: async () => ({ ...SCHEDULED, date: serverDay }),
      set: async (date, draft) => {
        calls.push(date);
        return { date, ...draft, source: 'manual' };
      },
    });
    const { result } = renderHook(() => useDayMode(api));
    await waitFor(() => expect(result.current.mode?.date).toBe('2026-10-26'));

    // The laptop slept through the boundary: the server is on the next day now.
    serverDay = '2026-10-27';
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await waitFor(() => expect(result.current.mode?.date).toBe('2026-10-27'));
    await act(async () => {
      await result.current.decide('sick', false);
    });

    expect(calls).toEqual(['2026-10-27']);
  });
});
