'use client';
// [review:need-review] PHASE-03/160
// summary: state of the day's activity block — one read of the three readings together, a correction and a manual record that both re-read the day rather than patching the list, and an idempotency key minted once per submission so a retry cannot become a second record

import { useCallback, useEffect, useState } from 'react';
import {
  agentAPI,
  type ActivityDay,
  type ActivityIntervalPatch,
  type ManualIntervalDraft,
} from '@/lib/api';

/** Shown when the day's activity cannot be read at all. */
export const LOAD_ACTIVITY_ERROR = 'Не удалось загрузить активность дня';

export interface UseDayActivityResult {
  day: ActivityDay | null;
  loading: boolean;
  saving: boolean;
  error: string | null;
  patch: (id: number, patch: ActivityIntervalPatch) => Promise<void>;
  addManual: (draft: ManualIntervalDraft) => Promise<void>;
}

/**
 * The activity of one day.
 *
 * Every write re-reads the whole day rather than patching the list it holds.
 * Moving the ends of one interval changes the roll-up per task, and that number
 * is the union of ranges — it cannot be recomputed in the browser from the rows
 * on screen without becoming a second, larger answer to the same question.
 */
export function useDayActivity(date: string): UseDayActivityResult {
  const [day, setDay] = useState<ActivityDay | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshCounter, setRefreshCounter] = useState(0);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const body = await agentAPI.day(date);
        if (!cancelled) setDay(body);
      } catch (err) {
        if (cancelled) return;
        setDay(null);
        setError(err instanceof Error ? err.message : LOAD_ACTIVITY_ERROR);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [date, refreshCounter]);

  const write = useCallback(async (act: () => Promise<unknown>) => {
    setSaving(true);
    setError(null);
    try {
      await act();
      setRefreshCounter((n) => n + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : LOAD_ACTIVITY_ERROR);
    } finally {
      setSaving(false);
    }
  }, []);

  const patch = useCallback(
    (id: number, body: ActivityIntervalPatch) =>
      write(() => agentAPI.patchInterval(id, body)),
    [write]
  );

  const addManual = useCallback(
    (draft: ManualIntervalDraft) => {
      // Минтуется один раз на отправку: повтор того же запроса после обрыва
      // должен вернуть ту же строку, а не завести вторую.
      const key = crypto.randomUUID();
      return write(() => agentAPI.addManualInterval(draft, key));
    },
    [write]
  );

  return { day, loading, saving, error, patch, addManual };
}
