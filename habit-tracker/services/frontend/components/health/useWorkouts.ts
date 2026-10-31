'use client';
// [review:need-review] PHASE-02/70, PHASE-03/303
// summary: reads the workouts of the last 30 days for the Health screens once on mount; a failed read leaves the workouts section out, as the sleep section does, so the catalog below never breaks on it

import { useEffect, useState } from 'react';
// A namespace import read at call time: suites that mock `@/lib/api` with a
// fixed list of names keep linking every screen that renders Health.
import * as api from '@/lib/api';
import type { HealthWorkout, HealthWorkoutsResponse } from '@/lib/api';
import { localDate } from '@/lib/health-metrics';
import { shiftDate } from './useSleepNights';

/** Today and the 29 days before it. */
export const WORKOUT_WINDOW_DAYS = 30;

export type WorkoutsRead = (dateFrom: string, dateTo: string) => Promise<HealthWorkoutsResponse>;

const API_READ: WorkoutsRead = (dateFrom, dateTo) => api.healthAPI.getWorkouts(dateFrom, dateTo);

/** The workouts of the window, oldest first; null before the answer and after a failed read. */
export function useWorkouts(read: WorkoutsRead = API_READ): HealthWorkout[] | null {
  const [workouts, setWorkouts] = useState<HealthWorkout[] | null>(null);

  useEffect(() => {
    let alive = true;
    const today = localDate();
    // `Promise.resolve().then` also turns a synchronous throw from `read` into a rejection.
    Promise.resolve()
      .then(() => read(shiftDate(today, 1 - WORKOUT_WINDOW_DAYS), today))
      .then((body) => {
        if (alive) setWorkouts(body.workouts);
      })
      .catch(() => {
        // Workouts are one section of the screen; its failure must not take the rest down.
      });
    return () => {
      alive = false;
    };
  }, [read]);

  return workouts;
}
