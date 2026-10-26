// [review:need-review] PHASE-03/162
// summary: the badge of the day mode on Today — the kind in a list and no-code as a separate switch (a working Tuesday is both), who decided (schedule or hand), a way back to the schedule for a day decided by hand, and a link to the week schedule

import Link from 'next/link';
import type { DayMode, DayModeKind } from '@/lib/api';
import { KIND_OPTIONS, NOCODE_LABEL, RESET_LABEL, sourceLabel } from '@/lib/day-mode';

export const MODE_SCHEDULE_HREF = '/agent/mode-schedule';

export interface DayModeBadgeProps {
  /** Null until the first answer; nothing is drawn for it. */
  mode: DayMode | null;
  saving: boolean;
  error: string | null;
  onDecide: (kind: DayModeKind, nocode: boolean) => void;
  onReset: () => void;
}

export default function DayModeBadge({ mode, saving, error, onDecide, onReset }: DayModeBadgeProps) {
  if (mode === null) return null;
  return (
    <div
      data-source={mode.source}
      className="flex flex-wrap items-center gap-3 rounded-3xl border border-white/5 bg-surface px-4 py-3 text-sm"
    >
      <select
        aria-label="Вид дня"
        value={mode.kind}
        disabled={saving}
        onChange={(event) => onDecide(event.target.value as DayModeKind, mode.nocode)}
        className="rounded-xl bg-card border border-white/10 px-2 py-1 text-text-primary"
      >
        {KIND_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <label className="inline-flex items-center gap-2 text-text-primary">
        <input
          type="checkbox"
          checked={mode.nocode}
          disabled={saving}
          onChange={() => onDecide(mode.kind, !mode.nocode)}
        />
        {NOCODE_LABEL}
      </label>
      <span className="text-text-secondary">{sourceLabel(mode.source)}</span>
      {mode.source === 'manual' && (
        <button
          type="button"
          disabled={saving}
          onClick={onReset}
          className="text-lime hover:underline disabled:opacity-50"
        >
          {RESET_LABEL}
        </button>
      )}
      <Link href={MODE_SCHEDULE_HREF} className="ml-auto text-text-secondary hover:text-text-primary">
        Расписание
      </Link>
      {error !== null && (
        <p role="alert" className="basis-full text-warning">
          {error}
        </p>
      )}
    </div>
  );
}
