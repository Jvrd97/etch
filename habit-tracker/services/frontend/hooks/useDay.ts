'use client';
// [review:need-review] PHASE-03/86
// summary: day-screen state for both shells — one fetch of the day and the rule it is judged by, with "today" left to the server so the browser calendar never decides which day is open

import { useCallback, useEffect, useState } from 'react';
import { dayAPI, type DayDetail } from '@/lib/api';
import { LOAD_DAY_ERROR } from '@/lib/day-format';

/** Everything a day screen needs; the two shells differ only in markup. */
export interface UseDayResult {
  /** The day and its rule, or null while loading or after a failure. */
  detail: DayDetail | null;
  loading: boolean;
  error: string | null;
  /** Re-fetch the day, e.g. after it was edited elsewhere. */
  reload: () => void;
}

/**
 * The day at `date`, or today when `date` is null.
 *
 * Null means "ask the server which day it is" rather than "read the browser's
 * calendar": the day runs from 04:00, so between midnight and four the two
 * disagree, and the screen would open a day nothing else is writing into.
 */
export function useDay(date: string | null): UseDayResult {
  const [detail, setDetail] = useState<DayDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshCounter, setRefreshCounter] = useState(0);

  useEffect(() => {
    // The screen may unmount, or be pointed at another date, while the request
    // is in flight; without this its result would overwrite the newer one.
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      // Cleared up front rather than on success: a banner from a date that
      // failed must not follow the reader onto the one that loaded fine.
      setError(null);
      try {
        const result = date === null
          ? await dayAPI.getToday()
          : await dayAPI.get(date);
        if (cancelled) return;
        setDetail(result);
      } catch (err) {
        if (cancelled) return;
        setDetail(null);
        setError(err instanceof Error ? err.message : LOAD_DAY_ERROR);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [date, refreshCounter]);

  const reload = useCallback(() => {
    setRefreshCounter((n) => n + 1);
  }, []);

  return { detail, loading, error, reload };
}
