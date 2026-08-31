// [review:need-review] PHASE-03/87
// summary: the day's clock — every line that claimed a window, in order, with the duration the server measured, a point shown as one time with a dash for its length, and collisions highlighted from the server's own self-join rather than from a comparison here

import { AlertTriangle, Clock } from 'lucide-react';
import type { ScheduleEntry, ScheduleOverlap } from '@/lib/api';
import { formatMinutes } from '@/lib/day-format';
import {
  EMPTY_SCHEDULE_TEXT,
  OVERLAP_BADGE,
  formatWindow,
  overlappingItemIds,
  scheduleDuration,
  totalOverlapMinutes,
} from '@/lib/plan';

export interface DayScheduleProps {
  schedule: ScheduleEntry[];
  overlaps: ScheduleOverlap[];
  /** Mobile trims the type scale; the structure is identical. */
  compact?: boolean;
}

/**
 * What the day claims of the clock, and where it claims the same minute twice.
 *
 * The collisions are the server's answer, not this component's. Two windows
 * intersect if `plan_item.window && plan_item.window` says so over a GiST
 * index; recomputing that here would put the truth about a plan in the one
 * place that cannot be queried, and would drift the moment a window crosses
 * midnight — which the browser has no way to reason about.
 */
export default function DaySchedule({
  schedule,
  overlaps,
  compact = false,
}: DayScheduleProps) {
  const colliding = overlappingItemIds(overlaps);
  const doubleBooked = totalOverlapMinutes(overlaps);

  return (
    <section
      className={`bg-card border border-white/5 rounded-3xl ${compact ? 'p-4' : 'p-6'}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2
          className={`font-semibold text-text-primary ${compact ? 'text-base' : 'text-xl'}`}
        >
          Расписание дня
        </h2>
        {overlaps.length > 0 && (
          <span className="inline-flex items-center gap-2 px-3 py-1 rounded-2xl bg-surface text-sm text-warning">
            <AlertTriangle className="w-4 h-4" strokeWidth={2} />
            {overlaps.length} {OVERLAP_BADGE} · {formatMinutes(doubleBooked)}
          </span>
        )}
      </div>

      {schedule.length === 0 ? (
        <p className="mt-3 text-text-secondary">{EMPTY_SCHEDULE_TEXT}</p>
      ) : (
        <ol className={compact ? 'mt-3 space-y-2' : 'mt-4 space-y-3'}>
          {schedule.map((entry) => {
            const collides = colliding.has(entry.item_id);
            return (
              <li
                key={entry.item_id}
                className={`flex items-start gap-3 rounded-2xl px-3 py-2 ${
                  collides ? 'bg-surface' : ''
                }`}
              >
                <span
                  className={`font-mono text-sm shrink-0 ${
                    collides ? 'text-warning' : 'text-text-secondary'
                  }`}
                >
                  {formatWindow(entry.starts_at, entry.ends_at)}
                </span>
                <span className="min-w-0 flex-1 text-text-primary text-sm">
                  {entry.code && (
                    <span className="font-mono text-xs text-text-secondary mr-2">
                      {entry.code}
                    </span>
                  )}
                  {entry.text_plain}
                  {entry.window_comment && (
                    <span className="text-text-disabled"> — {entry.window_comment}</span>
                  )}
                </span>
                <span className="inline-flex items-center gap-1.5 shrink-0 text-sm text-text-secondary">
                  <Clock className="w-4 h-4" strokeWidth={2} />
                  {scheduleDuration(entry.minutes)}
                </span>
                {collides && (
                  <span className="shrink-0 text-xs text-warning">{OVERLAP_BADGE}</span>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
