'use client';
// [review:need-review] PHASE-03/94, #311
// summary: one fetch of a week — by its ISO code, or the current one when the code is null so the server's day boundary decides which week is running
// summary: #311 — the week is a key of the shared read cache: a re-visit draws it at once and re-reads it behind the screen

import { weeksAPI, type Week } from '@/lib/api';
import { useQuery } from '@/lib/query-cache';

/** Said when the week could not be read at all. */
export const LOAD_WEEK_ERROR = 'Не удалось загрузить неделю';

export interface UseWeekResult {
  week: Week | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

/**
 * The week `iso`, or the current one when `iso` is null.
 *
 * Null means "ask the server which week it is" rather than "read the browser's
 * calendar": the day runs from 04:00, so in the small hours of Monday the two
 * disagree and the page would open a week the day is not in.
 */
export function useWeek(iso: string | null): UseWeekResult {
  const { state, refresh } = useQuery(`week:${iso ?? 'current'}`, () =>
    iso === null ? weeksAPI.getCurrent() : weeksAPI.get(iso)
  );
  const failure = state.status === 'error' ? state.error : null;
  return {
    week: state.status === 'ready' ? state.data : null,
    loading: state.status === 'loading',
    error: failure === null ? null : failure instanceof Error ? failure.message : LOAD_WEEK_ERROR,
    reload: () => void refresh(),
  };
}
