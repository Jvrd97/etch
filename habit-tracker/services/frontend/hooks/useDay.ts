'use client';
// [review:need-review] PHASE-03/86, PHASE-03/88, PHASE-03/147
// summary: day-screen state for both shells — one fetch of the day, the rule it is judged by and its marks, with "today" left to the server so the browser calendar never decides which day is open, an explicit flag saying a person is looking at it, the rules this day's plan broke fetched beside the day so a `warn` is visible on the line it belongs to, and a reload of a day already on screen kept silent instead of replacing it with a spinner

import { useCallback, useEffect, useRef, useState } from 'react';
import { dayAPI, type DayDetail, type PlanViolation } from '@/lib/api';
import { LOAD_DAY_ERROR } from '@/lib/day-format';

/** Everything a day screen needs; the two shells differ only in markup. */
export interface UseDayResult {
  /** The day and its rule, or null while loading or after a failure. */
  detail: DayDetail | null;
  /** True only while the screen has nothing to show — a first read or a new date. */
  loading: boolean;
  /**
   * True while a day already on screen is being re-read.
   *
   * Separate from `loading` because the two ask for different things from a
   * screen: `loading` says "there is nothing to draw yet", `refreshing` says
   * "what you see is one round trip out of date". A single flag made every
   * write — a mark, an anchor, an interval — replace the whole day with a
   * spinner, which reads as the page reloading itself under the finger.
   */
  refreshing: boolean;
  error: string | null;
  /**
   * The rules this day's plan broke, empty when it broke none.
   *
   * Fetched beside the day rather than folded into it: a failure to read the
   * violations must not blank the day itself — a plan with an unknown number of
   * warnings is still a plan a person is living.
   */
  violations: PlanViolation[];
  /** Re-fetch the day, e.g. after it was edited elsewhere. */
  reload: () => void;
}

/**
 * The day at `date`, or today when `date` is null.
 *
 * Null means "ask the server which day it is" rather than "read the browser's
 * calendar": the day runs from 04:00, so between midnight and four the two
 * disagree, and the screen would open a day nothing else is writing into.
 *
 * `opened` says that a person is looking at this day, and it is what fills
 * `day.opened_at`. Off by default: an agent, an import and a cron job read days
 * too, and if reading counted as opening then "не открывал" — one of the four
 * kinds of empty the day screen has to tell apart — would stop being a fact
 * anything could establish.
 */
export function useDay(date: string | null, opened = false): UseDayResult {
  const [detail, setDetail] = useState<DayDetail | null>(null);
  const [violations, setViolations] = useState<PlanViolation[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshCounter, setRefreshCounter] = useState(0);
  // Which date is currently drawn, as a key. Empty until one is: a failed read
  // leaves nothing on screen, so the retry after it is a first read again and
  // has to show the spinner rather than a silent refresh of nothing.
  // `String(null)` is 'null' — a stable key for "today", distinct from empty.
  const shownKey = useRef('');

  useEffect(() => {
    // The screen may unmount, or be pointed at another date, while the request
    // is in flight; without this its result would overwrite the newer one.
    let cancelled = false;

    const load = async () => {
      // The same day again — a reload after a write: keep it on screen and say
      // it is refreshing. A different day, or none yet: nothing can be drawn,
      // so this is a real load and the screen waits.
      const silent = shownKey.current === String(date);
      if (silent) setRefreshing(true);
      else setLoading(true);
      // Cleared up front rather than on success: a banner from a date that
      // failed must not follow the reader onto the one that loaded fine.
      setError(null);
      try {
        const result = date === null
          ? await (opened ? dayAPI.openToday() : dayAPI.getToday())
          : await (opened ? dayAPI.open(date) : dayAPI.get(date));
        if (cancelled) return;
        setDetail(result);
        shownKey.current = String(date);
        // Its own failure, swallowed on purpose: the day loaded, and an empty
        // list of warnings is a worse answer than no day only in theory.
        const found = await dayAPI
          .violations(result.day.date)
          .catch(() => [] as PlanViolation[]);
        if (cancelled) return;
        setViolations(found);
      } catch (err) {
        if (cancelled) return;
        shownKey.current = '';
        setDetail(null);
        setViolations([]);
        setError(err instanceof Error ? err.message : LOAD_DAY_ERROR);
      } finally {
        if (cancelled) return;
        setLoading(false);
        setRefreshing(false);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [date, opened, refreshCounter]);

  const reload = useCallback(() => {
    setRefreshCounter((n) => n + 1);
  }, []);

  return { detail, loading, refreshing, error, violations, reload };
}
