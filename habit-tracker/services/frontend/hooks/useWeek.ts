'use client';
// [review:need-review] PHASE-03/94
// summary: one fetch of a week — by its ISO code, or the current one when the code is null so the server's day boundary decides which week is running

import { useCallback, useEffect, useState } from 'react';
import { weeksAPI, type Week } from '@/lib/api';

/** Said when the week could not be read at all. */
export const LOAD_WEEK_ERROR = 'Не удалось загрузить неделю';

export interface UseWeekResult {
  week: Week | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

/**
 * The week `iso`, or the current one when `iso` is null.
 *
 * Null means "ask the server which week it is" rather than "read the browser's
 * calendar": the day runs from 04:00, so in the small hours of Monday the two
 * disagree and the page would open a week the day is not in.
 */
export function useWeek(iso: string | null): UseWeekResult {
  const [week, setWeek] = useState<Week | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshCounter, setRefreshCounter] = useState(0);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const result = iso === null ? await weeksAPI.getCurrent() : await weeksAPI.get(iso);
        if (cancelled) return;
        setWeek(result);
      } catch (err) {
        if (cancelled) return;
        setWeek(null);
        setError(err instanceof Error ? err.message : LOAD_WEEK_ERROR);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [iso, refreshCounter]);

  const reload = useCallback(() => {
    setRefreshCounter((n) => n + 1);
  }, []);

  return { week, loading, error, reload };
}
