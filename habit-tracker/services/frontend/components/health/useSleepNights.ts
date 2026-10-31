'use client';
// [review:need-review] PHASE-03/238, PHASE-02/69, PHASE-03/277
// summary: reads the nights of sleep for the Health screens — the last seven by default, or the range a detail screen names; a failed read is logged and leaves the sleep section out, as the sync block does, so the catalog below never breaks on it

import { useEffect, useState } from 'react';
// A namespace import read at call time: suites that mock `@/lib/api` with a
// fixed list of names keep linking every screen that renders Health.
import * as api from '@/lib/api';
import type { HealthSleepResponse, HealthSleepNight } from '@/lib/api';
import { shiftDate } from '@/lib/health';
import { localDate } from '@/lib/health-metrics';

/** Today and the six nights before it. */
export const SLEEP_WINDOW_NIGHTS = 7;

export type SleepRead = (dateFrom: string, dateTo: string) => Promise<HealthSleepResponse>;

const API_READ: SleepRead = (dateFrom, dateTo) => api.healthAPI.getSleep(dateFrom, dateTo);

export { shiftDate };

/** The nights of the window, oldest first; null before the answer and after a failed read. */
export function useSleepNights(
  read: SleepRead = API_READ,
  range?: { from: string; to: string }
): HealthSleepNight[] | null {
  const [nights, setNights] = useState<HealthSleepNight[] | null>(null);
  const from = range?.from;
  const to = range?.to;

  useEffect(() => {
    let alive = true;
    const today = localDate();
    const dateTo = to ?? today;
    const dateFrom = from ?? shiftDate(today, 1 - SLEEP_WINDOW_NIGHTS);
    // `Promise.resolve().then` also turns a synchronous throw from `read` into a rejection.
    Promise.resolve()
      .then(() => read(dateFrom, dateTo))
      .then((body) => {
        if (alive) setNights(body.nights);
      })
      .catch((error: unknown) => {
        // Sleep is one section of the screen; its failure must not take the rest down.
        console.warn('сон не прочитался, секцию сна не показываем', error);
      });
    return () => {
      alive = false;
    };
  }, [read, from, to]);

  return nights;
}
