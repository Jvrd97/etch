'use client';
// [review:need-review] PHASE-03/91
// summary: the work block of the day screen — the intervals with their sum, a form that adds one by wall clock (an end before its start is the next morning), the running interval said out loud, a corrected interval showing both its value and the agent's, and «время не измерено» where a day has no intervals at all

import { useState } from 'react';
import { Trash2 } from 'lucide-react';
import type { WorkDay, WorkInterval } from '@/lib/api';
import { formatMinutes } from '@/lib/day-format';
import {
  AGENT_PROPOSED,
  NEW_INTERVAL_ID,
  NOT_MEASURED,
  RUNNING_LABEL,
  crossesMidnight,
  momentOf,
  proposedLabel,
  sourceLabel,
  spanLabel,
} from '@/lib/work-intervals';

export const WORK_TITLE = 'Время работы';
export const ADD_INTERVAL = 'Добавить';
export const STOP_INTERVAL = 'Остановить';
export const REMOVE_INTERVAL = 'Убрать интервал';
export const FROM_LABEL = 'С';
export const TO_LABEL = 'По';
export const BAD_CLOCK = 'Время вводится как 09:30';
export const EMPTY_HINT =
  'Ни одного интервала. Пока время не измерено, переработка не проверяется — ' +
  'и день от неё не проигрывает.';

export interface WorkIntervalsProps {
  work: WorkDay;
  saving: Set<string>;
  error: string | null;
  onAdd: (started_at: string, ended_at: string | null) => Promise<void>;
  onStop: (intervalId: string, ended_at: string) => Promise<void>;
  onRemove: (intervalId: string) => Promise<void>;
  /** Tighter spacing for the mobile shell; the markup is the same. */
  compact?: boolean;
}

/**
 * The measured time of one day.
 *
 * Three things this block refuses to do. It never shows an unmeasured day as
 * «0 ч» — the absence of intervals is said out loud, because a zero would read
 * as a day nobody worked. It never hides that an interval is still running: an
 * open one says «идёт» and offers to stop it at the current clock. And it never
 * shows a corrected interval alone — what the agent proposed stays beside the
 * value a person put there, or «исправил руками» and «агент так и посчитал»
 * become the same thing on screen.
 *
 * There is nothing here that could display a window title: the day model has no
 * column for one, and the API answer carries none.
 */
export default function WorkIntervals({
  work,
  saving,
  error,
  onAdd,
  onStop,
  onRemove,
  compact = false,
}: WorkIntervalsProps) {
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [clockError, setClockError] = useState<string | null>(null);

  const submit = async () => {
    const started = momentOf(work.day_date, from);
    if (started === null) {
      setClockError(BAD_CLOCK);
      return;
    }
    // An end earlier than its start is the next morning — 23:00 → 01:00 is one
    // interval, and the day it belongs to is the server's to decide.
    const ended =
      to.trim() === ''
        ? null
        : momentOf(work.day_date, to, crossesMidnight(from, to));
    if (to.trim() !== '' && ended === null) {
      setClockError(BAD_CLOCK);
      return;
    }
    setClockError(null);
    await onAdd(started, ended);
    setFrom('');
    setTo('');
  };

  const stop = async (interval: WorkInterval) => {
    const now = new Date();
    await onStop(interval.id, now.toISOString());
  };

  const padding = compact ? 'p-4' : 'p-6';

  return (
    <section className={`bg-card border border-white/5 rounded-3xl ${padding}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2
          className={`${compact ? 'text-base' : 'text-xl'} font-semibold text-text-primary`}
        >
          {WORK_TITLE}
        </h2>
        <span className="text-text-secondary">
          {work.work_minutes === null
            ? NOT_MEASURED
            : formatMinutes(work.work_minutes)}
          {work.running && ` · ${RUNNING_LABEL}`}
        </span>
      </div>

      {work.intervals.length === 0 ? (
        <p className="mt-3 text-sm text-text-secondary">{EMPTY_HINT}</p>
      ) : (
        <ul className="mt-4 space-y-3">
          {work.intervals.map((interval) => {
            const proposed = proposedLabel(interval);
            return (
              <li
                key={interval.id}
                className="flex flex-wrap items-baseline gap-x-4 gap-y-1 border-b border-white/5 pb-3 last:border-b-0"
              >
                <span className="text-text-primary tabular-nums">
                  {spanLabel(interval)}
                </span>
                <span className="text-text-secondary">
                  {interval.mode === 'off'
                    ? 'пауза'
                    : formatMinutes(interval.minutes)}
                </span>
                <span className="px-2 py-0.5 rounded-2xl bg-surface text-xs text-text-secondary">
                  {sourceLabel(interval.source)}
                </span>
                {proposed !== null && (
                  <span className="text-xs text-text-secondary">
                    {AGENT_PROPOSED}: {proposed}
                  </span>
                )}
                {interval.note && (
                  <span className="text-sm text-text-secondary">
                    {interval.note}
                  </span>
                )}
                <span className="ml-auto flex items-center gap-3">
                  {interval.running && (
                    <button
                      type="button"
                      disabled={saving.has(interval.id)}
                      onClick={() => void stop(interval)}
                      className="rounded-2xl bg-surface px-3 py-1 text-sm text-text-primary disabled:opacity-50"
                    >
                      {STOP_INTERVAL}
                    </button>
                  )}
                  <button
                    type="button"
                    aria-label={`${REMOVE_INTERVAL} ${spanLabel(interval)}`}
                    disabled={saving.has(interval.id)}
                    onClick={() => void onRemove(interval.id)}
                    className="text-text-disabled hover:text-warning disabled:opacity-50"
                  >
                    <Trash2 className="w-4 h-4" strokeWidth={2} />
                  </button>
                </span>
              </li>
            );
          })}
        </ul>
      )}

      <div className="mt-5 flex flex-wrap items-end gap-3">
        <label className="text-sm text-text-secondary">
          {FROM_LABEL}
          <input
            type="text"
            inputMode="numeric"
            value={from}
            aria-label={FROM_LABEL}
            placeholder="09:30"
            onChange={(event) => setFrom(event.target.value)}
            className="mt-1 block w-24 bg-surface rounded-2xl px-3 py-2 text-text-primary tabular-nums placeholder:text-text-disabled"
          />
        </label>
        <label className="text-sm text-text-secondary">
          {TO_LABEL}
          <input
            type="text"
            inputMode="numeric"
            value={to}
            aria-label={TO_LABEL}
            placeholder="13:00"
            onChange={(event) => setTo(event.target.value)}
            className="mt-1 block w-24 bg-surface rounded-2xl px-3 py-2 text-text-primary tabular-nums placeholder:text-text-disabled"
          />
        </label>
        <button
          type="button"
          disabled={from.trim() === '' || saving.has(NEW_INTERVAL_ID)}
          onClick={() => void submit()}
          className="rounded-2xl bg-surface px-4 py-2 text-text-primary disabled:opacity-50"
        >
          {ADD_INTERVAL}
        </button>
      </div>

      {clockError && <p className="mt-3 text-sm text-warning">{clockError}</p>}
      {error && <p className="mt-3 text-sm text-warning">{error}</p>}
    </section>
  );
}
