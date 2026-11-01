'use client';
// [review:need-review] PHASE-03/86, PHASE-03/88, PHASE-03/147, #311
// summary: day-screen state for both shells — one fetch of the day, the rule it is judged by and its marks, with "today" left to the server so the browser calendar never decides which day is open, an explicit flag saying a person is looking at it, the rules this day's plan broke fetched beside the day so a `warn` is visible on the line it belongs to, and a reload of a day already on screen kept silent instead of replacing it with a spinner

// summary: #311 round 3 — a cached «today» is drawn at once, but `writeDate` stays '' (writes locked) until the server has confirmed the day within DAY_TRUST_MS; a failed re-read is reported, and the key tells a read from an opening
// summary: #311 — the day and its violations are two keys of the shared read cache: a re-visit draws the day at once and re-reads it behind the screen, and the first frame no longer waits for the violations
import { useCallback, useState } from 'react';
import { dayAPI, type DayDetail, type PlanViolation } from '@/lib/api';
import { LOAD_DAY_ERROR } from '@/lib/day-format';
import { errorMessage, useQuery } from '@/lib/query-cache';
import { DAY_TRUST_MS } from '@/hooks/useServerDay';

const NO_VIOLATIONS: PlanViolation[] = [];

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
  /**
   * The date writes may go to, or '' while they must wait.
   *
   * A named date is always writable. «Today» drawn from the cache is shown at
   * once, but it may be yesterday (the day turns at 04:00): its date is offered
   * to writers only once the server confirmed it within DAY_TRUST_MS, so a tick
   * in the first frame cannot land in a day that has ended. A re-read that
   * failed leaves it locked.
   */
  writeDate: string;
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
  // `today` is a key of its own: which day it is stays the server's answer. A
  // cached «today» is drawn at once (the screen opens instantly) and writes wait
  // for the server's confirmation — see `writeDate`.
  const day = useQuery(`day:${date ?? 'today'}${opened ? ':opened' : ''}`, () =>
    date === null
      ? opened ? dayAPI.openToday() : dayAPI.getToday()
      : opened ? dayAPI.open(date) : dayAPI.get(date)
  );
  const [mountedAt] = useState(() => Date.now());
  const detail = day.state.status === 'ready' ? day.state.data : null;
  const shownDate = detail?.day.date ?? null;
  // Its own key and its own failure, swallowed on purpose: the day is drawn without
  // waiting for it, and an empty list of warnings is a worse answer than no day only in theory.
  const found = useQuery(shownDate === null ? null : `violations:${shownDate}`, () =>
    shownDate === null ? Promise.resolve(NO_VIOLATIONS) : dayAPI.violations(shownDate)
  );

  const refreshDay = day.refresh;
  const refreshViolations = found.refresh;
  const reload = useCallback(() => {
    void refreshDay();
    void refreshViolations();
  }, [refreshDay, refreshViolations]);

  return {
    detail,
    loading: day.state.status === 'loading',
    refreshing: day.state.status === 'ready' && day.state.refreshing,
    // A failed re-read is said too: the screen must not keep writing into a day it cannot confirm.
    error: errorMessage(day.state, LOAD_DAY_ERROR),
    violations: found.state.status === 'ready' ? found.state.data : NO_VIOLATIONS,
    reload,
    writeDate:
      detail === null || day.state.status !== 'ready'
        ? ''
        : date !== null || day.state.answeredAt >= mountedAt - DAY_TRUST_MS
          ? detail.day.date
          : '',
  };
}
