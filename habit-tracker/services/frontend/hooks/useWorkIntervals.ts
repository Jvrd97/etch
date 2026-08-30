'use client';
// [review:need-review] PHASE-03/91
// summary: work-interval state for both day shells — the day's intervals with their sum, add/edit/remove writing straight through and re-reading the server's answer, and a sum that is never invented locally because an open interval's length is the server's to count

import { useCallback, useEffect, useState } from 'react';
import { dayAPI, type WorkDay, type WorkIntervalDraft, type WorkIntervalPatch } from '@/lib/api';
import { NEW_INTERVAL_ID, SAVE_INTERVAL_ERROR } from '@/lib/work-intervals';

export interface UseWorkIntervalsResult {
  /** The day's intervals and their sum; `work_minutes: null` — не измерено. */
  work: WorkDay;
  /** An id with a write in flight, so the row can say it is saving. */
  saving: Set<string>;
  busy: boolean;
  error: string | null;
  add: (draft: WorkIntervalDraft) => Promise<void>;
  edit: (intervalId: string, patch: WorkIntervalPatch) => Promise<void>;
  remove: (intervalId: string) => Promise<void>;
}

/**
 * The intervals of one day.
 *
 * Unlike marks, nothing here is applied optimistically. The length of an
 * interval — and therefore the sum of the day — is counted by the server: an
 * open one runs to now and stops at the end of its own day, which the browser
 * does not know where to put. Guessing it locally would put one number on the
 * screen and another in the verdict beside it.
 *
 * `initial` seeds the block from the day that was already fetched, so the list
 * renders with the page rather than a round trip later.
 */
export function useWorkIntervals(
  date: string,
  initial: WorkDay
): UseWorkIntervalsResult {
  const [work, setWork] = useState<WorkDay>(initial);
  const [saving, setSaving] = useState<Set<string>>(() => new Set());
  const [error, setError] = useState<string | null>(null);

  // The day was re-read (another date, a reload): the server's answer replaces
  // whatever this hook was holding.
  useEffect(() => {
    setWork(initial);
    setError(null);
  }, [initial]);

  const run = useCallback(
    async (id: string, write: () => Promise<unknown>) => {
      setSaving((current) => new Set(current).add(id));
      setError(null);
      try {
        await write();
        // Re-read rather than patch in place: the sum, the running flag and the
        // agent's kept values are all the server's to recompute.
        setWork(await dayAPI.workIntervals(date));
      } catch (err) {
        setError(err instanceof Error ? err.message : SAVE_INTERVAL_ERROR);
      } finally {
        setSaving((current) => {
          const next = new Set(current);
          next.delete(id);
          return next;
        });
      }
    },
    [date]
  );

  const add = useCallback(
    async (draft: WorkIntervalDraft) => {
      await run(NEW_INTERVAL_ID, () => dayAPI.addWorkInterval(date, draft));
    },
    [date, run]
  );

  const edit = useCallback(
    async (intervalId: string, patch: WorkIntervalPatch) => {
      await run(intervalId, () =>
        dayAPI.updateWorkInterval(date, intervalId, patch)
      );
    },
    [date, run]
  );

  const remove = useCallback(
    async (intervalId: string) => {
      await run(intervalId, () => dayAPI.deleteWorkInterval(date, intervalId));
    },
    [date, run]
  );

  return {
    work,
    saving,
    busy: saving.size > 0,
    error,
    add,
    edit,
    remove,
  };
}
