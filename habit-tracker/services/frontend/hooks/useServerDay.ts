'use client';
// [review:need-review] PHASE-03/252
// summary: the day the server is running (GET /day-mode, boundary at 04:00) for every screen outside Today that used to ask the browser's clock: `readServerDay` joins a read started in the same render pass, `useServerDay` reads it on mount and when the tab comes back and returns '' while the day is unknown (a silent writer refuses to guess; `settled` says the wait is over), `useDisplayDay` falls back to the browser's day for screens that only show it; these screens do not follow the 04:00 boundary while they stay open (no timer, only the tab coming back)

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useRefreshOnVisible } from '@/hooks/useRefreshOnVisible';
// A namespace import read at call time, as in `useDayMode`: suites that mock
// `@/lib/api` with a fixed list of names must still link every screen.
import * as api from '@/lib/api';
import { todayISO } from '@/lib/date';

/**
 * The read the readers of one render pass share.
 *
 * A page mounts several readers at once (the chart, the chat sheet, a form), and
 * their effects run one after another in the same synchronous pass: one request
 * answers all of them. The slot is emptied as soon as that pass ends, so a later
 * question is always asked anew and a read that never returns cannot stand in
 * for it.
 */
let sharedRead: Promise<string> | null = null;

/** The server's day as `YYYY-MM-DD`; rejects when the server cannot be asked. */
export function readServerDay(): Promise<string> {
  if (sharedRead !== null) return sharedRead;
  const day = Promise.resolve()
    .then(() => api.agentAPI.dayMode())
    .then((mode) => mode.date);
  sharedRead = day;
  queueMicrotask(() => {
    sharedRead = null;
  });
  return day;
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
  const [state, setState] = useState<ServerDay>({ date: '', settled: false });

  const read = useCallback(() => {
    // A screen whose caller pinned the day (tests) asks nobody.
    if (!enabled) return;
    readServerDay().then(
      (date) => setState({ date, settled: true }),
      // A lost read keeps the day already known (see above); nothing is shown for it.
      () => setState((previous) => ({ ...previous, settled: true }))
    );
  }, [enabled]);

  useEffect(read, [read]);
  useRefreshOnVisible(read);

  return state;
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
