'use client';
// [review:need-review] PHASE-03/160
// summary: «где прошёл день» on the day screen — the tape of intervals with a pencil that corrects one in place, the roll-up per application, the roll-up per task taken from the server because it is a union rather than a sum, the row of work outside any task, «заголовок скрыт правилом» with a link to the rules, and a form that adds a record by hand

import { useState } from 'react';
import Link from 'next/link';
import { Pencil, Plus } from 'lucide-react';
import ErrorAlert from '@/components/ErrorAlert';
import LoadingSpinner from '@/components/LoadingSpinner';
import IntervalEditor from '@/components/agent/IntervalEditor';
import { useDayActivity } from '@/hooks/useDayActivity';
import { formatMinutes } from '@/lib/day-format';
import {
  APPS_TITLE,
  CORRECTED_MARK,
  DAY_ACTIVITY_TITLE,
  EMPTY_ACTIVITY_TEXT,
  TAPE_TITLE,
  TASKS_TITLE,
  TITLE_HIDDEN_TEXT,
  TITLE_RULES_HREF,
  TITLE_RULES_LINK_TEXT,
  UNTASKED_HINT,
  UNTASKED_LABEL,
  hasUntasked,
  intervalClock,
  intervalLength,
  intervalSource,
  taskLabel,
  titleIsHidden,
} from '@/lib/interval-rollup';

export const EDIT_INTERVAL_LABEL = 'Править интервал';
export const ADD_MANUAL_LABEL = 'Добавить запись руками';

export interface DayIntervalsProps {
  /** `YYYY-MM-DD` — the day the block is about. */
  date: string;
  /** Mobile trims the type scale; the structure is identical. */
  compact?: boolean;
}

/**
 * Where the day went, in the three readings that answer different questions.
 *
 * The tape says when; the applications say in what; the tasks say on what. Only
 * the third is counted by the union of ranges, and it is taken from the server
 * whole — adding the drawn rows up in the browser would print a larger number
 * beside the same list, which is precisely the confusion this block exists to
 * end.
 */
export default function DayIntervals({ date, compact = false }: DayIntervalsProps) {
  const { day, loading, saving, error, patch, addManual } = useDayActivity(date);
  const [openId, setOpenId] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);
  const [from, setFrom] = useState('10:00');
  const [to, setTo] = useState('11:00');
  const [note, setNote] = useState('');

  if (loading) return <LoadingSpinner />;

  const card = `bg-card border border-white/5 rounded-3xl ${compact ? 'p-4' : 'p-6'}`;
  const field =
    'w-full rounded-2xl bg-surface border border-white/10 px-3 py-2 text-sm text-text-primary';

  const submitManual = (event: React.FormEvent) => {
    event.preventDefault();
    void addManual({
      started_at: `${date}T${from}:00`,
      ended_at: `${date}T${to}:00`,
      local_date: date,
      note: note.trim() || null,
    });
    setNote('');
    setAdding(false);
  };

  return (
    <section className={card}>
      <div className="flex items-baseline justify-between gap-3">
        <h2 className={`text-text-primary ${compact ? 'text-base' : 'text-lg'}`}>
          {DAY_ACTIVITY_TITLE}
        </h2>
        {day && (
          <span className="text-xs text-text-secondary">
            всего {formatMinutes(day.total_minutes)}
          </span>
        )}
      </div>

      {error && <ErrorAlert message={error} />}

      {!day || day.intervals.length === 0 ? (
        <p className="text-sm text-text-secondary mt-3">{EMPTY_ACTIVITY_TEXT}</p>
      ) : (
        <div className="mt-4 space-y-5">
          <div>
            <h3 className="text-sm text-text-secondary">{APPS_TITLE}</h3>
            <ul className="mt-2 space-y-1">
              {day.apps.map((slice) => (
                <li
                  key={slice.app_name}
                  className="flex items-baseline justify-between gap-3 text-sm"
                >
                  <span className="text-text-primary">{slice.app_name}</span>
                  <span className="text-text-secondary">
                    {formatMinutes(slice.minutes)}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          <div>
            <h3 className="text-sm text-text-secondary">{TASKS_TITLE}</h3>
            <ul className="mt-2 space-y-1">
              {day.tasks.map((slice) => (
                <li
                  key={`${slice.plan_task_id}-${slice.clickup_task_id}`}
                  className="flex items-baseline justify-between gap-3 text-sm"
                >
                  <span className="text-text-primary">
                    {taskLabel(slice.plan_task_id, slice.clickup_task_id)}
                  </span>
                  <span className="text-text-secondary">
                    {formatMinutes(slice.minutes)}
                  </span>
                </li>
              ))}
              {hasUntasked(day) && (
                <li className="pt-1">
                  <div className="flex items-baseline justify-between gap-3 text-sm">
                    <span className="text-warning">{UNTASKED_LABEL}</span>
                    <span className="text-warning">
                      {formatMinutes(day.untasked_minutes)}
                    </span>
                  </div>
                  <p className="text-xs text-text-secondary">{UNTASKED_HINT}</p>
                </li>
              )}
            </ul>
          </div>

          <div>
            <h3 className="text-sm text-text-secondary">{TAPE_TITLE}</h3>
            <ul className="mt-2 space-y-2">
              {day.intervals.map((interval) => (
                <li key={interval.id} className="text-sm">
                  <div className="flex flex-wrap items-baseline gap-2">
                    <span className="font-mono text-xs text-text-secondary">
                      {intervalClock(interval)}
                    </span>
                    <span className="text-text-primary">
                      {intervalSource(interval)}
                    </span>
                    <span className="text-text-secondary">
                      {intervalLength(interval)}
                    </span>
                    {interval.is_corrected && (
                      <span className="px-2 py-0.5 rounded-2xl bg-surface text-xs text-lime">
                        {CORRECTED_MARK}
                      </span>
                    )}
                    <button
                      type="button"
                      aria-label={`${EDIT_INTERVAL_LABEL} ${intervalClock(interval)}`}
                      onClick={() =>
                        setOpenId(openId === interval.id ? null : interval.id)
                      }
                      className="rounded-2xl p-1 text-text-disabled hover:text-text-secondary"
                    >
                      <Pencil className="w-3.5 h-3.5" strokeWidth={2} />
                    </button>
                  </div>

                  {titleIsHidden(interval) && interval.source === 'agent' && (
                    // Не пустая ячейка: «заголовка нет» и «правило его не
                    // пропустило» — разные факты, и у второго есть адрес.
                    <p className="text-xs text-text-secondary">
                      {TITLE_HIDDEN_TEXT} ·{' '}
                      <Link href={TITLE_RULES_HREF} className="underline">
                        {TITLE_RULES_LINK_TEXT}
                      </Link>
                    </p>
                  )}
                  {interval.note && (
                    <p className="text-xs text-text-secondary">{interval.note}</p>
                  )}

                  {openId === interval.id && (
                    <IntervalEditor
                      interval={interval}
                      saving={saving}
                      onSave={(body) => {
                        void patch(interval.id, body);
                        setOpenId(null);
                      }}
                      onCancel={() => setOpenId(null)}
                    />
                  )}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {adding ? (
        <form onSubmit={submitManual} className="mt-4 space-y-2">
          <div className="flex flex-wrap gap-2">
            <label className="flex-1 min-w-[6rem]">
              <span className="text-xs text-text-disabled">Начало</span>
              <input
                className={field}
                value={from}
                onChange={(event) => setFrom(event.target.value)}
                aria-label="Начало записи"
              />
            </label>
            <label className="flex-1 min-w-[6rem]">
              <span className="text-xs text-text-disabled">Конец</span>
              <input
                className={field}
                value={to}
                onChange={(event) => setTo(event.target.value)}
                aria-label="Конец записи"
              />
            </label>
          </div>
          <label className="block">
            <span className="text-xs text-text-disabled">Что это было</span>
            <input
              className={field}
              value={note}
              placeholder="созвон"
              onChange={(event) => setNote(event.target.value)}
              aria-label="Что это было"
            />
          </label>
          <button
            type="submit"
            disabled={saving}
            className="text-sm px-4 py-2 rounded-xl bg-lime text-background disabled:opacity-50"
          >
            Записать
          </button>
        </form>
      ) : (
        <button
          type="button"
          onClick={() => setAdding(true)}
          className="mt-4 inline-flex items-center gap-1 rounded-2xl bg-surface px-3 py-1.5 text-sm text-text-secondary"
        >
          <Plus className="w-4 h-4" strokeWidth={2} />
          {ADD_MANUAL_LABEL}
        </button>
      )}
    </section>
  );
}
