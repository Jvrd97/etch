'use client';
// [review:need-review] PHASE-03/166
// summary: reads the measured time of the day on screen against its plan — once per day and again once a write of a done mark has settled, then every minute only while the day is the server's today; an answer for another day is never returned and a failed read leaves the blocks out instead of breaking the day

import { useEffect, useState } from 'react';
// A namespace import read at call time, as in `useClaudeUsage`: suites that mock
// `@/lib/api` with a fixed list of names must still link every screen of the day.
import * as api from '@/lib/api';
import type { TaskTimeDay } from '@/lib/api';

/** The agent flushes every few minutes; a minute keeps the numbers close enough. */
export const TASK_TIME_REFRESH_MS = 60_000;

/** The read and the pace, as parameters so tests need no module mock. Keep the object stable between renders. */
export interface TaskTimeSource {
  read: (date: string) => Promise<TaskTimeDay>;
  refreshMs: number;
}

const API_SOURCE: TaskTimeSource = {
  read: (date) => api.taskTimeAPI.day(date),
  refreshMs: TASK_TIME_REFRESH_MS,
};

/**
 * The task time of `date`, or null before the first answer, without a date, and
 * after a failed first read.
 *
 * `marksKey` changes when a task is ticked or unticked: the list of «done without
 * a trace» depends on the marks, and a block that waits a minute to notice a tick
 * looks broken. `null` means a mark is being written; the last settled key stays
 * in force, so the read comes once after the write.
 */
export function useTaskTime(
  date: string | null,
  marksKey: string | null,
  source: TaskTimeSource = API_SOURCE
): TaskTimeDay | null {
  const [taskTime, setTaskTime] = useState<TaskTimeDay | null>(null);
  // Adjusting state while rendering: a null key (a write in flight) leaves the
  // last settled one in force, so the effect below does not run until the write is done.
  const [key, setKey] = useState(marksKey ?? '');
  if (marksKey !== null && marksKey !== key) setKey(marksKey);

  useEffect(() => {
    if (date === null) return;
    let alive = true;
    let timer: ReturnType<typeof setInterval> | null = null;
    const load = () => {
      // `then`, not a bare call: a source that throws before it returns a promise is caught too.
      Promise.resolve()
        .then(() => source.read(date))
        .then((body) => {
          if (!alive) return;
          setTaskTime(body);
          // Only the server's today still grows; the time of a past day is final.
          if (body.date !== body.today && timer !== null) {
            clearInterval(timer);
            timer = null;
          }
        })
        .catch(() => {
          // Keep what was shown: one lost read is not news about the day.
        });
    };
    load();
    timer = setInterval(load, source.refreshMs);
    return () => {
      alive = false;
      if (timer !== null) clearInterval(timer);
    };
  }, [date, key, source]);

  return taskTime !== null && taskTime.date === date ? taskTime : null;
}
