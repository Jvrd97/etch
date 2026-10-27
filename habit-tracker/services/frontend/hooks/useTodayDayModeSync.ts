'use client';
// [review:need-review] PHASE-03/247
// summary: keeps the day-mode badge on the day the Today screen is on — a day the screen moved to (found by the minute timer or a reload) and a day the server stopped confirming both make the badge read again, so a decision can never go to a day the header has left; the read joins one already on its way

import { useEffect, useRef } from 'react';
import type { UseDayModeResult } from '@/hooks/useDayMode';
import type { UseTodayResult } from '@/hooks/useToday';

/**
 * Call it next to `useToday` and `useDayMode(today.dayModeClient)`.
 *
 * `useDayMode` changes its mode only from the answers to its own reads (mount,
 * the tab coming back, a retry, the end of a write); the day that the minute
 * timer or `reload()` found never reaches it by itself. Without this, at the
 * boundary the header shows the new day while the badge still decides the old
 * one, and after three lost minute reads the screen refuses ticks while the
 * badge keeps writing.
 */
export function useTodayDayModeSync(
  today: Pick<UseTodayResult, 'date' | 'dayStale'>,
  dayMode: Pick<UseDayModeResult, 'reload' | 'mode'>
): void {
  const { date, dayStale } = today;
  const { reload, mode } = dayMode;
  const seenDate = useRef(date);
  // The day the badge already shows, read inside the effect without making it run again.
  const badgeDate = useRef(mode?.date ?? null);

  // Declared first: the effects of one render run in order, and the next one reads this.
  const modeDate = mode?.date ?? null;
  useEffect(() => {
    badgeDate.current = modeDate;
  }, [modeDate]);

  useEffect(() => {
    // The first answer is read by the badge itself; only a move from one known day to another is news.
    const moved = seenDate.current !== '' && date !== '' && seenDate.current !== date;
    seenDate.current = date;
    // A badge that heard the same answer (it joined the read that moved the screen) needs no second one.
    if (moved && badgeDate.current !== date) void reload();
  }, [date, reload]);

  // A day the server stopped confirming: the read fails the same way and locks the badge.
  useEffect(() => {
    if (dayStale) void reload();
  }, [dayStale, reload]);
}
