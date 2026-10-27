'use client';
// [review:need-review] PHASE-03/228
// summary: the day mode of the server's current day for the Today screen — read on mount without a date (the answer names the day), every decision or reset goes to the date of that answer and is replaced by the server's reply, the last mode kept when a write fails; a read that fails (or a client that throws before returning a promise) is reported as `loadFailed` and can be retried, and it is read again whenever the tab becomes visible so a page left open across the day boundary follows the server's day

import { useCallback, useEffect, useState } from 'react';
import { useRefreshOnVisible } from '@/hooks/useRefreshOnVisible';
// A namespace import read at call time, not a named import: suites that mock
// `@/lib/api` with a fixed list of names would fail to link every screen that
// renders Today if this hook imported a new client by name.
import * as api from '@/lib/api';
import type { DayMode, DayModeDraft, DayModeKind } from '@/lib/api';

/** The three calls the badge makes; a parameter so tests need no module mock. Keep the object stable between renders. */
export interface DayModeClient {
  /** No date is sent: which day is running is the server's answer, as for the quick marks. */
  read: () => Promise<DayMode>;
  set: (date: string, draft: DayModeDraft) => Promise<DayMode>;
  clear: (date: string) => Promise<DayMode>;
}

const API_CLIENT: DayModeClient = {
  read: () => api.agentAPI.dayMode(),
  set: (date, draft) => api.agentAPI.setDayMode(date, draft),
  clear: (date) => api.agentAPI.clearDayMode(date),
};

const WRITE_FAILED = 'Не удалось сохранить режим дня';

export interface UseDayModeResult {
  /** Null until the first answer, and while the read keeps failing. */
  mode: DayMode | null;
  saving: boolean;
  /** The last write did not go through. */
  error: string | null;
  /** The read of the mode did not go through; `reload` asks again. */
  loadFailed: boolean;
  reload: () => Promise<void>;
  /** Decide the date by hand; both fields go, because they are independent. */
  decide: (kind: DayModeKind, nocode: boolean) => Promise<void>;
  /** Give the date back to the schedule. */
  reset: () => Promise<void>;
}

export function useDayMode(client: DayModeClient = API_CLIENT): UseDayModeResult {
  const [mode, setMode] = useState<DayMode | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  // The date every write goes to: the one the server named in its answer.
  const date = mode?.date ?? null;

  const load = useCallback(
    async (isCurrent: () => boolean) => {
      try {
        // `await` inside `try` also turns a synchronous throw of the client into a failed read.
        const body = await client.read();
        if (!isCurrent()) return;
        setMode(body);
        setLoadFailed(false);
      } catch {
        if (isCurrent()) setLoadFailed(true);
      }
    },
    [client]
  );

  useEffect(() => {
    let alive = true;
    void load(() => alive);
    return () => {
      alive = false;
    };
  }, [load]);

  const reload = useCallback(() => load(() => true), [load]);
  // A page left open across the day boundary (a laptop asleep overnight) must not keep writing to yesterday.
  const refreshQuietly = useCallback(() => void reload(), [reload]);
  useRefreshOnVisible(refreshQuietly);

  const write = useCallback(async (call: () => Promise<DayMode>) => {
    setSaving(true);
    setError(null);
    try {
      setMode(await call());
    } catch {
      setError(WRITE_FAILED);
    } finally {
      setSaving(false);
    }
  }, []);

  const decide = useCallback(
    async (kind: DayModeKind, nocode: boolean) => {
      if (date !== null) await write(() => client.set(date, { kind, nocode }));
    },
    [client, date, write]
  );
  const reset = useCallback(async () => {
    if (date !== null) await write(() => client.clear(date));
  }, [client, date, write]);

  return { mode, saving, error, loadFailed, reload, decide, reset };
}
