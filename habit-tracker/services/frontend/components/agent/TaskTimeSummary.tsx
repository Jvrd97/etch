// [review:need-review] PHASE-03/166
// summary: the day's blocks that read measured time against the plan — tasks ticked done with no interval, untasked stretches of half an hour or more («работа вне плана» in the same hour), time tied by another id than a plan item, and the share of untasked intervals with the days it was really measured over; nothing is drawn when there is nothing to say

import type { TaskTimeDay } from '@/lib/api';
import { clockRange } from '@/lib/time';
import { formatMinutes } from '@/lib/day-format';
import {
  DONE_NO_TRACE_TITLE,
  LONG_UNTASKED_TITLE,
  OTHER_LINKED_NOTE,
  OTHER_LINKED_TITLE,
  SHARE_TITLE,
  doneNoTraceNote,
  hasTaskTimeSummary,
  sharePercent,
  shareWindowCaption,
} from '@/lib/task-time';

export interface TaskTimeSummaryProps {
  /** Null until the first answer; nothing is drawn for it. */
  taskTime: TaskTimeDay | null;
  /** The phone shell: tighter padding and type. */
  compact?: boolean;
}

export default function TaskTimeSummary({ taskTime, compact = false }: TaskTimeSummaryProps) {
  if (taskTime === null || !hasTaskTimeSummary(taskTime)) return null;
  const { done_without_traces: traceless, long_untasked: longUntasked, untasked_share: share } = taskTime;
  const percent = sharePercent(share);

  return (
    <section
      aria-label="Время и план"
      className={`rounded-3xl border border-white/5 bg-surface space-y-3 ${compact ? 'p-3' : 'p-4'}`}
    >
      {traceless.length > 0 && (
        <div>
          <h3 className="text-sm font-medium text-warning">
            {DONE_NO_TRACE_TITLE}
          </h3>
          <ul className="mt-1 text-sm text-text-primary space-y-0.5">
            {traceless.map((row) => (
              <li key={row.plan_item_id}>{row.title}</li>
            ))}
          </ul>
          <p className="mt-1 text-xs text-text-secondary">{doneNoTraceNote(taskTime.commits_checked)}</p>
        </div>
      )}

      {longUntasked.length > 0 && (
        <div>
          <h3 className="text-sm font-medium text-text-primary">{LONG_UNTASKED_TITLE}</h3>
          <ul className="mt-1 text-sm text-text-secondary space-y-0.5">
            {longUntasked.map((row) => (
              <li key={row.interval_id} className="tabular-nums">
                {clockRange(row.started_at, row.ended_at)} · {formatMinutes(row.minutes)} · {row.app_name}
              </li>
            ))}
          </ul>
        </div>
      )}

      {taskTime.other_linked_minutes > 0 && (
        <div>
          <h3 className="text-sm font-medium text-text-primary">{OTHER_LINKED_TITLE}</h3>
          <p className="mt-1 text-sm text-text-secondary tabular-nums">
            {formatMinutes(taskTime.other_linked_minutes)}
          </p>
          <p className="mt-1 text-xs text-text-secondary">{OTHER_LINKED_NOTE}</p>
        </div>
      )}

      {percent !== null && (
        <div>
          <h3 className="text-sm font-medium text-text-primary">{SHARE_TITLE}</h3>
          <p className="mt-1 text-sm text-text-secondary">
            <span className="font-medium text-text-primary tabular-nums">{percent}</span> интервалов
            без задачи {shareWindowCaption(share)}
          </p>
        </div>
      )}
    </section>
  );
}
