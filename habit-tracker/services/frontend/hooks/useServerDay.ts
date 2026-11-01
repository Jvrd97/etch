'use client';
// [review:need-review] PHASE-03/252, #311
// summary: the day the server is running (GET /day-mode, boundary at 04:00) for every screen outside Today that used to ask the browser's clock: `readServerDay` joins a read already in flight through the shared cache, `useServerDay` draws the last known day at once (a re-visited screen does not wait for it), reads it again on mount and when the tab comes back, and returns '' while the day is unknown (a silent writer refuses to guess; `settled` says the wait is over), `useDisplayDay` falls back to the browser's day for screens that only show it; these screens do not follow the 04:00 boundary while they stay open (no timer, only the tab coming back)

import { useMemo } from 'react';
// A namespace import read at call time, as in `useDayMode`: suites that mock
// `@/lib/api` with a fixed list of names must still link every screen.
import * as api from '@/lib/api';
import { todayISO } from '@/lib/date';
import { fetchQuery, useQuery } from '@/lib/query-cache';

/** The cache key of the server's day. */
export const SERVER_DAY_KEY = 'serverDay';

function askServerDay(): Promise<string> {
  return api.agentAPI.dayMode().then((mode) => mode.date);
}

/**
 * The server's day as `YYYY-MM-DD`; rejects when the server cannot be asked.
 *
 * Joins a read already out (a page mounts several readers at once, and one
 * request answers all of them); otherwise it asks anew, because the day can
 * have turned since the last answer.
 */
export function readServerDay(): Promise<string> {
  return fetchQuery(SERVER_DAY_KEY, askServerDay);
}

const LOCAL_NOON_HOUR = 12;

export interface ServerDay {
  /**
   * The server's current day, or '' until the first answer (and while the read
   * keeps failing). The last known day stays on a failed re-read: it is the best
   * answer there is, and a screen that blanks its dates over one lost request is
   * worse than one that is a day late for a minute.
   */
  date: string;
  /** The first read has finished, with an answer or without: waiting for it any longer is pointless. */
  settled: boolean;
}

export function useServerDay(enabled = true): ServerDay {
  // A screen whose caller pinned the day (tests) asks nobody.
  const { state } = useQuery(enabled ? SERVER_DAY_KEY : null, askServerDay, { refreshOnVisible: true });
  // A lost re-read keeps the day already known (see above); nothing is shown for it.
  if (state.status === 'ready') return { date: state.data, settled: true };
  return { date: '', settled: enabled && state.status === 'error' };
}

/**
 * The day a screen only displays or compares against (a chart's streak, the
 * grouping of a chat list, a date prefilled into a form the reader can change):
 * the server's, and the browser's own until the server has named it or while it
 * cannot be asked. A screen that writes in silence must use `useServerDay` and
 * refuse to guess instead.
 */
export function useDisplayDay(enabled = true): string {
  const { date } = useServerDay(enabled);
  return date !== '' ? date : todayISO();
}

/**
 * `useDisplayDay` as a `Date` for the screens that compute with one (a year
 * range, a calendar cursor): local noon of that day, which no zone or daylight
 * switch moves to another date. A `pinned` date (tests) is returned as it is and
 * the server is not asked.
 */
export function useDisplayDate(pinned?: Date): Date {
  const day = useDisplayDay(pinned === undefined);
  return useMemo(() => {
    if (pinned !== undefined) return pinned;
    const [year, month, dayOfMonth] = day.split('-').map(Number);
    return new Date(year, month - 1, dayOfMonth, LOCAL_NOON_HOUR);
  }, [pinned, day]);
}
