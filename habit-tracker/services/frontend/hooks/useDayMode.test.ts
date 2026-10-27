// [review:need-review] PHASE-03/241
// summary: tests for useDayMode — the server's current day is read on mount and every write goes to the date of that answer (never a browser date), a decision is replaced by the server's answer, a reset takes the day back to the schedule, a failed write keeps the last mode and says so, a failed read (also a client that throws before returning a promise) is reported and can be retried, a tab that comes back after the day boundary reads the new day and writes to it, a re-read that failed leaves no write to the stale date, and a read that overlapped a write never overwrites its answer (and is asked again after the write when it was dropped)

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

  it('does not write to a stale date when the read on return failed', async () => {
    const sent: string[] = [];
    let failing = false;
    const api = client({
      read: async () => {
        if (failing) throw new Error('offline');
        return { ...SCHEDULED, date: '2026-10-26' };
      },
      set: async (date, draft) => {
        sent.push(`set ${date}`);
        return { date, ...draft, source: 'manual' };
      },
      clear: async (date) => {
        sent.push(`clear ${date}`);
        return { ...SCHEDULED, date };
      },
    });
    const { result } = renderHook(() => useDayMode(api));
    await waitFor(() => expect(result.current.mode?.date).toBe('2026-10-26'));

    failing = true;
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await waitFor(() => expect(result.current.loadFailed).toBe(true));
    // The old mode stays on screen, but it is yesterday's: nothing may go to it.
    expect(result.current.mode?.date).toBe('2026-10-26');
    await act(async () => {
      await result.current.decide('sick', false);
      await result.current.reset();
    });

    expect(sent).toEqual([]);
    expect(result.current.saving).toBe(false);

    failing = false;
    await act(async () => {
      await result.current.reload();
    });
    expect(result.current.loadFailed).toBe(false);
    await act(async () => {
      await result.current.decide('sick', false);
    });
    expect(sent).toEqual(['set 2026-10-26']);
  });

  it('drops a read that started before the write ended, so the answer of the write stays', async () => {
    let releaseRead: (mode: DayMode) => void = () => {};
    let reads = 0;
    let server = SCHEDULED;
    const api = client({
      read: () => {
        reads += 1;
        // The first read is the mount one; the second is held until after the write; the server answers the rest as it stands.
        if (reads !== 2) return Promise.resolve(server);
        return new Promise<DayMode>((resolve) => {
          releaseRead = resolve;
        });
      },
      set: async (_date, draft) => {
        server = { date: DATE, ...draft, source: 'manual' };
        return server;
      },
    });
    const { result } = renderHook(() => useDayMode(api));
    await waitFor(() => expect(result.current.mode).not.toBeNull());

    // The tab regains focus: a read starts, and its answer will be the old mode.
    act(() => {
      window.dispatchEvent(new Event('focus'));
    });
    await waitFor(() => expect(reads).toBe(2));
    await act(async () => {
      await result.current.decide('work', false);
    });
    expect(result.current.mode?.nocode).toBe(false);

    await act(async () => {
      releaseRead(SCHEDULED);
    });

    expect(result.current.mode?.nocode).toBe(false);
    expect(result.current.mode?.source).toBe('manual');
  });

  it('drops a read that started while a write was running', async () => {
    let releaseWrite: () => void = () => {};
    let releaseRead: (mode: DayMode) => void = () => {};
    let reads = 0;
    let server = SCHEDULED;
    const api = client({
      read: () => {
        reads += 1;
        if (reads !== 2) return Promise.resolve(server);
        return new Promise<DayMode>((resolve) => {
          releaseRead = resolve;
        });
      },
      set: (_date, draft) =>
        new Promise<DayMode>((resolve) => {
          releaseWrite = () => {
            server = { date: DATE, ...draft, source: 'manual' };
            resolve(server);
          };
        }),
    });
    const { result } = renderHook(() => useDayMode(api));
    await waitFor(() => expect(result.current.mode).not.toBeNull());

    let writing: Promise<void> = Promise.resolve();
    act(() => {
      writing = result.current.decide('work', false);
    });
    await waitFor(() => expect(result.current.saving).toBe(true));
    // A read begun during the write; its answer is the mode from before the write.
    act(() => {
      void result.current.reload();
    });
    await waitFor(() => expect(reads).toBe(2));
    await act(async () => {
      releaseWrite();
      await writing;
    });
    await act(async () => {
      releaseRead(SCHEDULED);
    });

    expect(result.current.mode?.nocode).toBe(false);
    expect(result.current.mode?.source).toBe('manual');
  });

  it('asks again after the write when the read that crossed the day boundary was dropped', async () => {
    let releaseRead: (mode: DayMode) => void = () => {};
    let reads = 0;
    const sent: string[] = [];
    const api = client({
      read: () => {
        reads += 1;
        if (reads === 1) return Promise.resolve({ ...SCHEDULED, date: '2026-10-26' });
        if (reads === 2) {
          return new Promise<DayMode>((resolve) => {
            releaseRead = resolve;
          });
        }
        return Promise.resolve({ ...SCHEDULED, date: '2026-10-27' });
      },
      set: async (date, draft) => {
        sent.push(date);
        return { date, ...draft, source: 'manual' };
      },
    });
    const { result } = renderHook(() => useDayMode(api));
    await waitFor(() => expect(result.current.mode?.date).toBe('2026-10-26'));

    // After midnight the tab returns and a read starts; while it is on the way, the person decides.
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await waitFor(() => expect(reads).toBe(2));
    await act(async () => {
      await result.current.decide('work', false);
    });
    expect(sent).toEqual(['2026-10-26']);
    // The read answers with the new day, but it overlapped the write and is dropped...
    await act(async () => {
      releaseRead({ ...SCHEDULED, date: '2026-10-27' });
    });
    // ...so the hook asks again by itself once the write is over.
    await waitFor(() => expect(result.current.mode?.date).toBe('2026-10-27'));
    await act(async () => {
      await result.current.decide('sick', false);
    });

    expect(sent).toEqual(['2026-10-26', '2026-10-27']);
  });

  it('takes a read that started after the write ended', async () => {
    let served = SCHEDULED;
    const api = client({ read: async () => served });
    const { result } = renderHook(() => useDayMode(api));
    await waitFor(() => expect(result.current.mode).not.toBeNull());
    await act(async () => {
      await result.current.decide('work', false);
    });

    served = { ...SCHEDULED, kind: 'sick', nocode: false, source: 'manual' };
    await act(async () => {
      await result.current.reload();
    });

    expect(result.current.mode?.kind).toBe('sick');
  });
});
