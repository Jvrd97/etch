// [review:need-review] PHASE-03/91
// summary: pure helpers of the work-interval list — a wall-clock HH:MM turned into a moment of the day being edited (an end earlier than its start means the next morning), the clock read back out of a moment by `lib/time`, and the labels the block renders

import type { WorkInterval } from '@/lib/api';
import { clock } from '@/lib/time';

/** Said when the server refused an interval; the row is rolled back under it. */
export const SAVE_INTERVAL_ERROR = 'Интервал не сохранился';

/**
 * The id a write with no row of its own yet is tracked under.
 *
 * A real interval id is a uuid, so nothing collides with it; the hook marks the
 * add form as saving under this and the form reads the same name.
 */
export const NEW_INTERVAL_ID = 'new';

/** Shown where the sum would be while the day has no intervals at all. */
export const NOT_MEASURED = 'время не измерено';

/** An interval with no end is not a broken one — it is the one running now. */
export const RUNNING_LABEL = 'идёт';

/** Said above the agent's original values on a corrected interval. */
export const AGENT_PROPOSED = 'Агент предлагал';

/** How each source reads on screen. */
const SOURCE_LABEL: Record<string, string> = {
  manual: 'руками',
  agent: 'агент',
  corrected: 'исправлено',
};

export function sourceLabel(source: string): string {
  return SOURCE_LABEL[source] ?? source;
}

const MINUTES_PER_DAY = 24 * 60;

/**
 * A wall-clock `HH:MM` of `date` as an instant, with the browser's offset.
 *
 * The person types the clock they lived by, and the offset comes from the
 * machine they are typing on. Which *day* the interval then belongs to is not
 * decided here and never is: the server asks `local_date()`, whose boundary is
 * a column of the canon and not something a browser can know.
 *
 * `endsNextMorning` is the one piece of arithmetic this function does: an end
 * earlier than its start (23:00 → 01:00) is the next calendar morning, because
 * an interval that ends before it begins is a typo the server refuses.
 */
export function momentOf(
  date: string,
  wallClock: string,
  endsNextMorning = false
): string | null {
  const parts = /^(\d{1,2}):(\d{2})$/.exec(wallClock.trim());
  if (parts === null) return null;
  const hours = Number(parts[1]);
  const minutes = Number(parts[2]);
  if (hours > 23 || minutes > 59) return null;

  const day = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  if (day === null) return null;

  const at = new Date(
    Number(day[1]),
    Number(day[2]) - 1,
    Number(day[3]) + (endsNextMorning ? 1 : 0),
    hours,
    minutes
  );
  return at.toISOString();
}

/** Whether `end` names an earlier clock than `start` — an interval past midnight. */
export function crossesMidnight(start: string, end: string): boolean {
  const from = clockMinutes(start);
  const to = clockMinutes(end);
  if (from === null || to === null) return false;
  return to <= from;
}

function clockMinutes(wallClock: string): number | null {
  const parts = /^(\d{1,2}):(\d{2})$/.exec(wallClock.trim());
  if (parts === null) return null;
  const value = Number(parts[1]) * 60 + Number(parts[2]);
  return value < MINUTES_PER_DAY ? value : null;
}

/** `09:30 – 13:00`, or `09:30 – идёт` while the interval is still running. */
export function spanLabel(interval: WorkInterval): string {
  const from = clock(interval.started_at);
  const to =
    interval.ended_at === null ? RUNNING_LABEL : clock(interval.ended_at);
  return `${from} – ${to}`;
}

/**
 * What the agent proposed, when it proposed anything.
 *
 * Returns null on every interval nobody corrected — including all the ones a
 * person typed themselves, which never had a proposal to keep.
 */
export function proposedLabel(interval: WorkInterval): string | null {
  if (interval.auto_started_at === null && interval.auto_ended_at === null) {
    return null;
  }
  const from =
    interval.auto_started_at === null ? '?' : clock(interval.auto_started_at);
  const to =
    interval.auto_ended_at === null
      ? RUNNING_LABEL
      : clock(interval.auto_ended_at);
  return `${from} – ${to}`;
}
