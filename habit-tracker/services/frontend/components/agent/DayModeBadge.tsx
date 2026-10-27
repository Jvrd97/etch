// [review:need-review] PHASE-03/249
// summary: the badge of the day mode on Today — the kind in a list and no-code as a separate switch (a working Tuesday is both), who decided (schedule or hand), a way back to the schedule for a day decided by hand, and a link to the week schedule; a read that failed is said aloud with a retry instead of leaving the badge out; since #241 also when a mode is already on screen (it may be yesterday's): the controls are locked until a read goes through; since #249 also while a re-read is on its way (`reading`), so a decision cannot go to yesterday's date

import Link from 'next/link';
import type { DayMode, DayModeKind } from '@/lib/api';
import { KIND_OPTIONS, NOCODE_LABEL, RESET_LABEL, sourceLabel } from '@/lib/day-mode';

export const MODE_SCHEDULE_HREF = '/agent/mode-schedule';

export interface DayModeBadgeProps {
  /** Null while the first answer is awaited, and after a failed read. */
  mode: DayMode | null;
  saving: boolean;
  /** A read is on its way: the mode on screen may be yesterday's, so the controls wait for the answer. */
  reading: boolean;
  /** The last write failed. */
  error: string | null;
  /** The read failed: the badge says so and offers `onRetry`; a mode still shown is locked, it may be stale. */
  loadFailed: boolean;
  onDecide: (kind: DayModeKind, nocode: boolean) => void;
  onReset: () => void;
  onRetry: () => void;
}

const LOAD_FAILED = 'Не удалось прочитать режим дня';
const RETRY_LABEL = 'Повторить';

function LoadFailedNotice({ onRetry }: { onRetry: () => void }) {
  return (
    <>
      <p role="alert" className="text-warning">
        {LOAD_FAILED}
      </p>
      <button type="button" onClick={onRetry} className="text-lime hover:underline">
        {RETRY_LABEL}
      </button>
    </>
  );
}

export default function DayModeBadge({
  mode,
  saving,
  reading,
  error,
  loadFailed,
  onDecide,
  onReset,
  onRetry,
}: DayModeBadgeProps) {
  if (mode === null) {
    if (!loadFailed) return null;
    return (
      <div className="flex flex-wrap items-center gap-3 rounded-3xl border border-white/5 bg-surface px-4 py-3 text-sm">
        <LoadFailedNotice onRetry={onRetry} />
      </div>
    );
  }
  const locked = saving || reading || loadFailed;
  return (
    <div
      data-source={mode.source}
      className="flex flex-wrap items-center gap-3 rounded-3xl border border-white/5 bg-surface px-4 py-3 text-sm"
    >
      <select
        aria-label="Вид дня"
        value={mode.kind}
        disabled={locked}
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
          disabled={locked}
          onChange={() => onDecide(mode.kind, !mode.nocode)}
        />
        {NOCODE_LABEL}
      </label>
      <span className="text-text-secondary">{sourceLabel(mode.source)}</span>
      {mode.source === 'manual' && (
        <button
          type="button"
          disabled={locked}
          onClick={onReset}
          className="text-lime hover:underline disabled:opacity-50"
        >
          {RESET_LABEL}
        </button>
      )}
      <Link href={MODE_SCHEDULE_HREF} className="ml-auto text-text-secondary hover:text-text-primary">
        Расписание
      </Link>
      {loadFailed && (
        <div className="flex basis-full flex-wrap items-center gap-3">
          <LoadFailedNotice onRetry={onRetry} />
        </div>
      )}
      {error !== null && (
        <p role="alert" className="basis-full text-warning">
          {error}
        </p>
      )}
    </div>
  );
}
