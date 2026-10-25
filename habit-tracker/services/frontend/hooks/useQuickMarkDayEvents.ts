'use client';
// [review:need-review] PHASE-01/206
// summary: the sets of one category's day as the list reads them — one fetch per category, a re-read that keeps the old rows on screen until the new ones land, and a failure that names itself instead of showing an empty day

import { useCallback, useEffect, useState } from 'react';
import { quickMarksAPI, type QuickMarkDayEvent } from '@/lib/api';

/** What the reader sees when the sets did not arrive and the server said nothing more. */
export const DAY_EVENTS_FAILED = 'Подходы за сегодня не загрузились.';

/**
 * Where the read stands.
 *
 * A union rather than a loading flag and an error beside the rows: "no rows
 * yet", "no rows today" and "rows could not be read" are three different days,
 * and a pair of booleans cannot say which one the screen is in.
 */
export type DayEventsState =
  | { status: 'loading' }
  | { status: 'ready'; events: QuickMarkDayEvent[] }
  | { status: 'failed'; message: string };

export interface UseQuickMarkDayEventsResult {
  state: DayEventsState;
  /**
   * Read the sets again.
   *
   * A list that is already on screen stays there until the new one lands, so an
   * undo does not blank the rows the reader is looking at; only a failed read
   * goes back to loading, because there is nothing on screen to keep.
   */
  reload: () => void;
}

/**
 * The taps of one category today, each as its own row.
 *
 * Read from the journal rather than derived from the day's entries: an
 * increment folds its taps into one stored number, so the entries cannot say
 * how many sets made it up or when.
 */
export function useQuickMarkDayEvents(categoryId: number): UseQuickMarkDayEventsResult {
  const [state, setState] = useState<DayEventsState>({ status: 'loading' });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;

    quickMarksAPI.dayEvents(categoryId).then(
      (events) => {
        if (!cancelled) setState({ status: 'ready', events });
      },
      (err: unknown) => {
        if (!cancelled) {
          setState({
            status: 'failed',
            message: err instanceof Error ? err.message : DAY_EVENTS_FAILED,
          });
        }
      }
    );

    // A newer read, or a closed list, makes this answer stale: letting it land
    // would paint the rows of a moment the reader has already moved past.
    return () => {
      cancelled = true;
    };
  }, [categoryId, attempt]);

  const reload = useCallback(() => {
    setState((current) => (current.status === 'failed' ? { status: 'loading' } : current));
    setAttempt((n) => n + 1);
  }, []);

  return { state, reload };
}
