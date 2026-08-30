'use client';
// [review:need-review] PHASE-03/94
// summary: one square of the timeline in five visually distinct states — won is filled lime, lost is filled grey, «не закрыт» is an outline with nothing inside, an unrecorded past day is a faint fill and the future is bare; the square is a link to /day/{date}

import Link from 'next/link';
import { STATUS_LABEL, type DayStatus } from '@/lib/life';

/**
 * How each state is painted.
 *
 * The three states the ticket cares about have to differ **by eye, not by
 * shade**: «выигран» is a filled lime square, «проигран» is a filled grey one,
 * and «не закрыт» is an outline with an empty middle. Filled-versus-outlined is
 * a difference of shape; two greys would be a difference of brightness, which
 * is what the old page had and what nobody could read.
 */
const STATUS_CLASS: Record<DayStatus, string> = {
  won: 'bg-lime border-lime',
  lost: 'bg-text-disabled border-text-disabled',
  open: 'bg-transparent border-lime',
  empty: 'bg-white/5 border-white/5',
  future: 'bg-transparent border-white/10 border-dashed',
};

export interface DaySquareProps {
  /** `YYYY-MM-DD`, and the day the square links to. */
  date: string;
  status: DayStatus;
  /** Appended to the tooltip — the title of the plan, the task counter. */
  detail?: string;
  /** Ringed rather than coloured, so «сегодня» reads on top of any state. */
  isToday?: boolean;
  size?: 'sm' | 'md' | 'lg';
}

const SIZE_CLASS = {
  sm: 'w-2.5 h-2.5 rounded-[3px]',
  md: 'w-5 h-5 rounded-md',
  lg: 'w-9 h-9 rounded-lg',
};

export default function DaySquare({
  date,
  status,
  detail,
  isToday = false,
  size = 'md',
}: DaySquareProps) {
  const label = detail ? `${date} — ${STATUS_LABEL[status]} · ${detail}` : `${date} — ${STATUS_LABEL[status]}`;
  return (
    <Link
      href={`/day/${date}`}
      title={label}
      aria-label={label}
      data-status={status}
      data-date={date}
      className={`block border transition-transform duration-150 hover:scale-125 ${SIZE_CLASS[size]} ${STATUS_CLASS[status]} ${
        isToday ? 'ring-2 ring-offset-2 ring-offset-background ring-white/60' : ''
      }`}
    />
  );
}

/** The legend under the grid; the same five states, named out loud. */
export function DaySquareLegend() {
  const states: DayStatus[] = ['won', 'lost', 'open', 'empty', 'future'];
  return (
    <div className="flex flex-wrap gap-4 text-sm text-text-secondary">
      {states.map((status) => (
        <span key={status} className="inline-flex items-center gap-2">
          <i
            aria-hidden="true"
            className={`w-3 h-3 rounded-[3px] border ${STATUS_CLASS[status]}`}
          />
          {STATUS_LABEL[status]}
        </span>
      ))}
    </div>
  );
}
