// [review:need-review] PHASE-03/162
// summary: tests for useDayMode — the mode is read on mount, a decision is replaced by the server's answer, a reset takes the day back to the schedule, a failed write keeps the last mode and says so, a client that throws before returning a promise leaves the badge out instead of breaking the screen

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
  it('reads the mode of the date on mount', async () => {
    const { result } = renderHook(() => useDayMode(DATE, client()));

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
    const { result } = renderHook(() => useDayMode(DATE, api));
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
    const { result } = renderHook(() => useDayMode(DATE, api));
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
    const { result } = renderHook(() => useDayMode(DATE, api));
    await waitFor(() => expect(result.current.mode).not.toBeNull());

    await act(async () => {
      await result.current.decide('dayoff', false);
    });

    expect(result.current.mode).toEqual(SCHEDULED);
    expect(result.current.error).not.toBeNull();
  });

  it('stays null, without throwing, when the client throws before it returns a promise', async () => {
    const api = client({
      read: () => {
        throw new TypeError('agentAPI.dayMode is not a function');
      },
    });
    const { result } = renderHook(() => useDayMode(DATE, api));

    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(result.current.mode).toBeNull();
  });
});
