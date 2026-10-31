// [review:need-review] PHASE-03/166
// summary: the chip beside a task of the plan with the time the agent and the hand recorded on it — the union of the ranges that name the task, so two overlapping records are not counted twice; nothing is drawn for a task with no time

import { Timer } from 'lucide-react';
import { formatMinutes } from '@/lib/day-format';

export interface TaskTimeBadgeProps {
  /** Minutes on the task; zero or missing draws nothing. */
  minutes: number | undefined;
}

export default function TaskTimeBadge({ minutes }: TaskTimeBadgeProps) {
  if (minutes === undefined || minutes <= 0) return null;
  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-2xl bg-surface text-xs text-text-secondary tabular-nums"
      title="Время по задаче: объединение записанных интервалов"
    >
      <Timer className="w-3.5 h-3.5" strokeWidth={2} />
      {formatMinutes(minutes)}
    </span>
  );
}
