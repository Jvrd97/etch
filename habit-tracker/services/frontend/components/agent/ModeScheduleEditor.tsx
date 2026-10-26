'use client';
// [review:need-review] PHASE-03/162
// summary: the week schedule of the day mode — seven rows, Monday first, the kind in a list and no-code as its own switch per weekday, saved as one week; days decided by hand are not touched by a save, and the screen says so

import { useEffect, useState } from 'react';
// A namespace import read at call time (see hooks/useDayMode.ts): suites that
// mock `@/lib/api` by a fixed list of names must still link this screen.
import * as api from '@/lib/api';
import type { DayModeKind, ModeSchedule, ModeScheduleDay } from '@/lib/api';
import ErrorAlert from '@/components/ErrorAlert';
import LoadingSpinner from '@/components/LoadingSpinner';
import { KIND_OPTIONS, NOCODE_LABEL, WEEK_ORDER } from '@/lib/day-mode';

/** The two calls of the screen; a prop so tests need no module mock. Keep the object stable between renders. */
export interface ModeScheduleClient {
  read: () => Promise<ModeSchedule>;
  save: (week: ModeSchedule) => Promise<ModeSchedule>;
}

const API_CLIENT: ModeScheduleClient = {
  read: () => api.agentAPI.modeSchedule(),
  save: (week) => api.agentAPI.saveModeSchedule(week),
};

const LOAD_FAILED = 'Не удалось прочитать расписание';
const SAVE_FAILED = 'Не удалось сохранить расписание';

export default function ModeScheduleEditor({ client = API_CLIENT }: { client?: ModeScheduleClient }) {
  const [days, setDays] = useState<ModeScheduleDay[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    client
      .read()
      .then((week) => {
        if (alive) setDays(week.days);
      })
      .catch(() => {
        if (alive) setError(LOAD_FAILED);
      });
    return () => {
      alive = false;
    };
  }, [client]);

  const edit = (weekday: number, patch: Partial<Pick<ModeScheduleDay, 'kind' | 'nocode'>>) => {
    setSaved(false);
    setDays((current) =>
      current === null
        ? current
        : current.map((day) => (day.weekday === weekday ? { ...day, ...patch } : day))
    );
  };

  const save = async () => {
    if (days === null) return;
    setSaving(true);
    setError(null);
    try {
      const week = await client.save({ days });
      setDays(week.days);
      setSaved(true);
    } catch {
      setError(SAVE_FAILED);
    } finally {
      setSaving(false);
    }
  };

  if (days === null && error === null) return <LoadingSpinner />;

  return (
    <div className="space-y-6 max-w-xl">
      <div>
        <h1 className="text-3xl font-bold text-text-primary tracking-tight">Расписание режимов</h1>
        <p className="mt-2 text-text-secondary">
          Какой день недели по умолчанию. Дни, где режим решён вручную, расписание не меняет.
        </p>
      </div>
      {error !== null && <ErrorAlert message={error} onDismiss={() => setError(null)} />}
      {days !== null && (
        <>
          <ul className="space-y-2">
            {WEEK_ORDER.map(({ weekday, label }) => {
              const day = days.find((d) => d.weekday === weekday);
              if (day === undefined) return null;
              return (
                <li
                  key={weekday}
                  className="flex items-center gap-3 rounded-2xl border border-white/5 bg-surface px-4 py-2"
                >
                  <span className="w-32 text-text-primary">{label}</span>
                  <select
                    aria-label={`${label}: вид дня`}
                    value={day.kind}
                    disabled={saving}
                    onChange={(event) => edit(weekday, { kind: event.target.value as DayModeKind })}
                    className="rounded-xl bg-card border border-white/10 px-2 py-1 text-text-primary"
                  >
                    {KIND_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                  <label className="inline-flex items-center gap-2 text-text-secondary">
                    <input
                      type="checkbox"
                      aria-label={`${label}: ${NOCODE_LABEL}`}
                      checked={day.nocode}
                      disabled={saving}
                      onChange={() => edit(weekday, { nocode: !day.nocode })}
                    />
                    {NOCODE_LABEL}
                  </label>
                </li>
              );
            })}
          </ul>
          <div className="flex items-center gap-3">
            <button
              type="button"
              disabled={saving}
              onClick={() => void save()}
              className="rounded-2xl bg-lime px-4 py-2 font-medium text-black disabled:opacity-50"
            >
              Сохранить
            </button>
            {saved && <span className="text-sm text-text-secondary">Сохранено</span>}
          </div>
        </>
      )}
    </div>
  );
}
