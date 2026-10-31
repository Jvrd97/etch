'use client';
// [review:need-review] PHASE-03/249, PHASE-03/257
// summary: the day mode of the server's current day for the Today screen — read on mount without a date (the answer names the day), every decision or reset goes to the date of that answer and is replaced by the server's reply, the last mode kept when a write fails; a read that fails (or a client that throws before returning a promise) is reported as `loadFailed` and can be retried, and it is read again whenever the tab becomes visible so a page left open across the day boundary follows the server's day; since #241 a re-read that failed blocks decide/reset (the mode on screen may be yesterday's), and a read that started before the end of a write, or during it, is dropped so it cannot paint the old mode over the write's answer — and asked again once no write is running, so a page across the day boundary does not stay on yesterday's date; since #249 the write slot is taken synchronously (two decides in one tick send one write), decide/reset wait while a read is on its way (`reading`) so they cannot hit yesterday's date, `writing` counts the writes in flight, and the re-read after a write is not asked once the hook is unmounted; since #257 a read that does not answer within `READ_TIMEOUT_MS` is reported as failed (a hung connection must not lock the badge for good) and the retry after a failure asks anew instead of joining the hung request, reads are taken in the order they started (an older answer never overwrites a newer one, the failure of an older read is not news while a newer is on its way), and one `mounted` flag replaces the per-read `alive` check

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRefreshOnVisible } from '@/hooks/useRefreshOnVisible';
// A namespace import read at call time, not a named import: suites that mock
// `@/lib/api` with a fixed list of names would fail to link every screen that
// renders Today if this hook imported a new client by name.
import * as api from '@/lib/api';
import type { DayMode, DayModeDraft, DayModeKind } from '@/lib/api';

/** The three calls the badge makes; a parameter so tests need no module mock. Keep the object stable between renders. */
export interface DayModeClient {
  /**
   * No date is sent: which day is running is the server's answer, as for the quick marks.
   * `fresh` asks for a new request: the one still in flight may be the hung one that just failed the badge.
   */
  read: (options?: { fresh?: boolean }) => Promise<DayMode>;
  set: (date: string, draft: DayModeDraft) => Promise<DayMode>;
  clear: (date: string) => Promise<DayMode>;
}

const API_CLIENT: DayModeClient = {
  read: () => api.agentAPI.dayMode(),
  set: (date, draft) => api.agentAPI.setDayMode(date, draft),
  clear: (date) => api.agentAPI.clearDayMode(date),
};

const WRITE_FAILED = 'Не удалось сохранить режим дня';
/** A read that has not answered by now is lost (a laptop woken behind a captive portal keeps its TCP connection open for minutes). */
export const READ_TIMEOUT_MS = 10_000;

export interface UseDayModeResult {
  /** Null until the first answer, and while the read keeps failing. */
  mode: DayMode | null;
  saving: boolean;
  /** A read is on its way: the mode on screen may be yesterday's, so decide/reset do not go out until it answers. */
  reading: boolean;
  /** The last write did not go through. */
  error: string | null;
  /** The read of the mode did not go through (a mode already on screen may be yesterday's); `reload` asks again. */
  loadFailed: boolean;
  reload: () => Promise<void>;
  /** Decide the date by hand; both fields go, because they are independent. */
  decide: (kind: DayModeKind, nocode: boolean) => Promise<void>;
  /** Give the date back to the schedule. */
  reset: () => Promise<void>;
}

export function useDayMode(
  client: DayModeClient = API_CLIENT,
  readTimeoutMs: number = READ_TIMEOUT_MS
): UseDayModeResult {
  const [mode, setMode] = useState<DayMode | null>(null);
  const [saving, setSaving] = useState(false);
  const [reading, setReading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  // The date every write goes to: the one the server named in its answer.
  // After a failed re-read the mode on screen may be yesterday's: no write until a read goes through.
  const date = loadFailed ? null : (mode?.date ?? null);
  // Counts the starts and the ends of writes. A read whose answer finds the number changed (or a write still running) overlapped a write:
  // it was asked before the write ended, and its answer may be older than the write's.
  const writeGeneration = useRef(0);
  // Writes in flight. The slot is taken here, synchronously: `saving` only reaches the buttons after a render,
  // and two decides in one tick would both read it as false.
  const writing = useRef(0);
  // Reads in flight, for the same reason: a decide that starts while a read is on its way would go to its old date.
  const readsInFlight = useRef(0);
  const mounted = useRef(false);
  // A read was dropped because of a write; it is asked again when the write is over.
  const readDropped = useRef(false);
  // Numbers the reads in the order they start. The answer of a read is taken only if no newer read has been taken already.
  const readsStarted = useRef(0);
  const lastTaken = useRef(0);
  // The last read failed or timed out: the next one must not join the request that failed it.
  const lastReadLost = useRef(false);

  const load = useCallback(async (): Promise<void> => {
    const startedAt = writeGeneration.current;
    readsStarted.current += 1;
    const mine = readsStarted.current;
    let settled = false;
    // The slot of the read is given back once: by its answer or by the timeout, whichever comes first.
    const settle = (): void => {
      if (settled) return;
      settled = true;
      readsInFlight.current -= 1;
      setReading(readsInFlight.current > 0);
    };
    // The answer of a read that overlapped a write is dropped, not trusted: it may be older than the write's.
    const dropIfOverlapped = (): boolean => {
      if (!mounted.current) return true;
      if (writeGeneration.current === startedAt && writing.current === 0) return false;
      if (writing.current > 0) readDropped.current = true;
      else void load();
      return true;
    };
    const fresh = lastReadLost.current;
    readsInFlight.current += 1;
    setReading(true);
    const timer = setTimeout(() => {
      if (settled) return;
      settle();
      lastReadLost.current = true;
      if (mounted.current && mine === readsStarted.current) setLoadFailed(true);
    }, readTimeoutMs);
    try {
      // `await` inside `try` also turns a synchronous throw of the client into a failed read.
      const body = await client.read(fresh ? { fresh } : undefined);
      clearTimeout(timer);
      settle();
      lastReadLost.current = false;
      if (dropIfOverlapped() || mine < lastTaken.current) return;
      lastTaken.current = mine;
      setMode(body);
      setLoadFailed(false);
    } catch {
      clearTimeout(timer);
      // A read already reported by the timeout has nothing more to say.
      const reported = settled;
      settle();
      lastReadLost.current = true;
      // The failure of an older read is not news while a newer one is on its way.
      if (!reported && !dropIfOverlapped() && mine === readsStarted.current) setLoadFailed(true);
    }
  }, [client, readTimeoutMs]);

  useEffect(() => {
    mounted.current = true;
    void load();
    return () => {
      mounted.current = false;
    };
  }, [load]);

  const reload = useCallback(() => load(), [load]);
  // A page left open across the day boundary (a laptop asleep overnight) must not keep writing to yesterday.
  const refreshQuietly = useCallback(() => void load(), [load]);
  useRefreshOnVisible(refreshQuietly);

  const write = useCallback(
    async (call: () => Promise<DayMode>) => {
      if (writing.current > 0) return;
      writeGeneration.current += 1;
      writing.current += 1;
      setSaving(true);
      setError(null);
      try {
        setMode(await call());
      } catch {
        setError(WRITE_FAILED);
      } finally {
        writeGeneration.current += 1;
        writing.current -= 1;
        setSaving(writing.current > 0);
        if (readDropped.current) {
          readDropped.current = false;
          if (mounted.current) void load();
        }
      }
    },
    [load]
  );

  const decide = useCallback(
    async (kind: DayModeKind, nocode: boolean) => {
      if (date !== null && readsInFlight.current === 0) await write(() => client.set(date, { kind, nocode }));
    },
    [client, date, write]
  );
  const reset = useCallback(async () => {
    if (date !== null && readsInFlight.current === 0) await write(() => client.clear(date));
  }, [client, date, write]);

  return { mode, saving, reading, error, loadFailed, reload, decide, reset };
}
