'use client';
// [review:need-review] PHASE-03/162
// summary: the day mode of one date for the Today screen — read on mount, replaced by the server's answer to a decision or a reset, the last mode kept when a write fails; a read that fails (or a client that throws before returning a promise) leaves the badge out, because a badge must never break the day

import { useCallback, useEffect, useState } from 'react';
// A namespace import read at call time, not a named import: suites that mock
// `@/lib/api` with a fixed list of names would fail to link every screen that
// renders Today if this hook imported a new client by name.
import * as api from '@/lib/api';
import type { DayMode, DayModeDraft, DayModeKind } from '@/lib/api';

/** The three calls the badge makes; a parameter so tests need no module mock. Keep the object stable between renders. */
export interface DayModeClient {
  read: (date: string) => Promise<DayMode>;
  set: (date: string, draft: DayModeDraft) => Promise<DayMode>;
  clear: (date: string) => Promise<DayMode>;
}

const API_CLIENT: DayModeClient = {
  read: (date) => api.agentAPI.dayMode(date),
  set: (date, draft) => api.agentAPI.setDayMode(date, draft),
  clear: (date) => api.agentAPI.clearDayMode(date),
};

const WRITE_FAILED = 'Не удалось сохранить режим дня';

export interface UseDayModeResult {
  /** Null until the first answer, and for good if the read never works. */
  mode: DayMode | null;
  saving: boolean;
  error: string | null;
  /** Decide the date by hand; both fields go, because they are independent. */
  decide: (kind: DayModeKind, nocode: boolean) => Promise<void>;
  /** Give the date back to the schedule. */
  reset: () => Promise<void>;
}

export function useDayMode(date: string, client: DayModeClient = API_CLIENT): UseDayModeResult {
  const [mode, setMode] = useState<DayMode | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    // `Promise.resolve().then` turns a synchronous throw into a rejection too.
    Promise.resolve()
      .then(() => client.read(date))
      .then((body) => {
        if (alive) setMode(body);
      })
      .catch(() => {
        // No badge is better than a broken day.
      });
    return () => {
      alive = false;
    };
  }, [client, date]);

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
    (kind: DayModeKind, nocode: boolean) => write(() => client.set(date, { kind, nocode })),
    [client, date, write]
  );
  const reset = useCallback(() => write(() => client.clear(date)), [client, date, write]);

  return { mode, saving, error, decide, reset };
}
