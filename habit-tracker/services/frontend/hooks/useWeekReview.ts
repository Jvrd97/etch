'use client';
// [review:need-review] PHASE-03/221
// summary: one request for the whole week review plus the narrative the reader asks for — two discriminated states, the narrative dropped when the week changes, a stale answer never written over a newer one

import { useCallback, useEffect, useRef, useState } from 'react';
// A namespace import read at call time: other suites mock `@/lib/api` with a
// fixed list of names, and a named import of one they do not list would fail
// to link for every file that renders after them.
import * as api from '@/lib/api';
import type { WeekNarrative, WeekReview } from '@/lib/api';
import { narrativeErrorText } from '@/lib/week-review';

/** The two calls the screen makes; a parameter so tests need no module mock. */
export interface WeekReviewClient {
  get: (iso: string | null) => Promise<WeekReview>;
  narrative: (iso: string) => Promise<WeekNarrative>;
}

const API_CLIENT: WeekReviewClient = {
  get: (iso) => api.weekReviewAPI.get(iso),
  narrative: (iso) => api.weekReviewAPI.narrative(iso),
};

export const LOAD_WEEK_REVIEW_ERROR = 'Не удалось загрузить обзор недели';

export type WeekReviewState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; review: WeekReview };

export type NarrativeState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; text: string };

export interface UseWeekReviewResult {
  state: WeekReviewState;
  narrative: NarrativeState;
  reload: () => void;
  /** Ask the model for the words of the week that is on screen. */
  writeNarrative: () => void;
}

/**
 * The review of week `iso`, or of the running one when `iso` is null.
 *
 * Null means «ask the server which week it is»: the day turns at 04:00, so in
 * the small hours of Monday the browser's calendar names a week the day is not in.
 */
export function useWeekReview(
  iso: string | null,
  client: WeekReviewClient = API_CLIENT
): UseWeekReviewResult {
  const [state, setState] = useState<WeekReviewState>({ status: 'loading' });
  const [narrative, setNarrative] = useState<NarrativeState>({ status: 'idle' });
  const [refresh, setRefresh] = useState(0);
  // The week the screen shows now; an answer for another one is dropped.
  const shown = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setState({ status: 'loading' });
      setNarrative({ status: 'idle' });
      shown.current = null;
      try {
        const review = await client.get(iso);
        if (cancelled) return;
        shown.current = review.window.iso_code;
        setState({ status: 'ready', review });
      } catch (error) {
        if (cancelled) return;
        setState({
          status: 'error',
          message: error instanceof Error ? error.message : LOAD_WEEK_REVIEW_ERROR,
        });
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [iso, refresh, client]);

  const reload = useCallback(() => setRefresh((n) => n + 1), []);

  const writeNarrative = useCallback(() => {
    const code = shown.current;
    if (code === null) return;
    setNarrative({ status: 'loading' });
    client
      .narrative(code)
      .then((result) => {
        if (shown.current !== code) return;
        setNarrative({ status: 'ready', text: result.text });
      })
      .catch((error: unknown) => {
        if (shown.current !== code) return;
        setNarrative({ status: 'error', message: narrativeErrorText(error) });
      });
  }, [client]);

  return { state, narrative, reload, writeNarrative };
}
