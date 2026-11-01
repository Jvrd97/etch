'use client';
// [review:need-review] PHASE-03/94, #311
// summary: one fetch of a range of days for the timeline, the week page and the sidebar — the range is a string pair so a caller that rebuilds it every render does not put the screen in a loop
// summary: #311 — the range is a key of the shared read cache (the Life grid and its sidebar ask for the same one and share a request; a re-visit draws at once), and a range not known yet (`null`) reads nothing

import { daysAPI, type DayListItem } from '@/lib/api';
import { useQuery } from '@/lib/query-cache';

/** Said when the range could not be read; the screen shows it instead of an empty grid. */
export const LOAD_DAYS_ERROR = 'Не удалось загрузить дни';

const NO_DAYS: DayListItem[] = [];

export interface UseDaysResult {
  days: DayListItem[];
  loading: boolean;
  error: string | null;
  reload: () => void;
}

/**
 * The days of `[from, to]`, oldest first; nothing while either end is null.
 *
 * The key is built from the two date strings rather than from an object, because
 * the natural way to call this — `useDays(startOfYear(), today())` — rebuilds
 * the argument on every render, and a hook that only works when its caller
 * remembers to memoise is a trap rather than a hook.
 */
export function useDays(from: string | null, to: string | null): UseDaysResult {
  const known = from !== null && to !== null;
  const { state, refresh } = useQuery(known ? `days:${from}:${to}` : null, () =>
    known ? daysAPI.range(from, to) : Promise.resolve(NO_DAYS)
  );
  const failure = state.status === 'error' ? state.error : null;
  return {
    days: state.status === 'ready' ? state.data : NO_DAYS,
    loading: known && state.status === 'loading',
    error: failure === null ? null : failure instanceof Error ? failure.message : LOAD_DAYS_ERROR,
    reload: () => void refresh(),
  };
}
