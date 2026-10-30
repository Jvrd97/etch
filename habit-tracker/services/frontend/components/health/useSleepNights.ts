'use client';
// [review:need-review] PHASE-03/238
// summary: reads the last seven nights of sleep for the Health screens once on mount; a failed read leaves the sleep section out, as the sync block does, so the catalog below never breaks on it

import { useEffect, useState } from 'react';
// A namespace import read at call time: suites that mock `@/lib/api` with a
// fixed list of names keep linking every screen that renders Health.
import * as api from '@/lib/api';
import type { HealthSleepResponse, HealthSleepNight } from '@/lib/api';
import { localDate } from '@/lib/health-metrics';

/** Today and the six nights before it. */
export const SLEEP_WINDOW_NIGHTS = 7;

export type SleepRead = (dateFrom: string, dateTo: string) => Promise<HealthSleepResponse>;

const API_READ: SleepRead = (dateFrom, dateTo) => api.healthAPI.getSleep(dateFrom, dateTo);

/** `YYYY-MM-DD` shifted by whole days, on the calendar alone (no timezone arithmetic). */
export function shiftDate(isoDate: string, days: number): string {
  const moment = new Date(`${isoDate}T00:00:00Z`);
  moment.setUTCDate(moment.getUTCDate() + days);
  return moment.toISOString().slice(0, 10);
}

/** The nights of the window, oldest first; null before the answer and after a failed read. */
export function useSleepNights(read: SleepRead = API_READ): HealthSleepNight[] | null {
  const [nights, setNights] = useState<HealthSleepNight[] | null>(null);

  useEffect(() => {
    let alive = true;
    const today = localDate();
    // `Promise.resolve().then` also turns a synchronous throw from `read` into a rejection.
    Promise.resolve()
      .then(() => read(shiftDate(today, 1 - SLEEP_WINDOW_NIGHTS), today))
      .then((body) => {
        if (alive) setNights(body.nights);
      })
      .catch(() => {
        // Sleep is one section of the screen; its failure must not take the rest down.
      });
    return () => {
      alive = false;
    };
  }, [read]);

  return nights;
}
