'use client';
// [review:need-review] PHASE-03/94
// summary: one fetch of a range of days for the timeline, the week page and the sidebar — the range is a string pair so a caller that rebuilds it every render does not put the screen in a loop

import { useCallback, useEffect, useState } from 'react';
import { daysAPI, type DayListItem } from '@/lib/api';

/** Said when the range could not be read; the screen shows it instead of an empty grid. */
export const LOAD_DAYS_ERROR = 'Не удалось загрузить дни';

export interface UseDaysResult {
  days: DayListItem[];
  loading: boolean;
  error: string | null;
  reload: () => void;
}

/**
 * The days of `[from, to]`, oldest first.
 *
 * The effect keys off the two date strings rather than off an object, because
 * the natural way to call this — `useDays(startOfYear(), today())` — rebuilds
 * the argument on every render, and a hook that only works when its caller
 * remembers to memoise is a trap rather than a hook.
 */
export function useDays(from: string, to: string): UseDaysResult {
  const [days, setDays] = useState<DayListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshCounter, setRefreshCounter] = useState(0);

  useEffect(() => {
    // The screen may unmount, or be pointed at another range, while the request
    // is in flight; without this its result would overwrite the newer one.
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const result = await daysAPI.range(from, to);
        if (cancelled) return;
        setDays(result);
      } catch (err) {
        if (cancelled) return;
        setDays([]);
        setError(err instanceof Error ? err.message : LOAD_DAYS_ERROR);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [from, to, refreshCounter]);

  const reload = useCallback(() => {
    setRefreshCounter((n) => n + 1);
  }, []);

  return { days, loading, error, reload };
}
