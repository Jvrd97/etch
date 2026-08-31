'use client';
// [review:need-review] PHASE-03/134, PHASE-03/138
// summary: the role screen both shells draw — where today's minutes went (share bar per role, the target share always labelled a hypothesis), the acts of the day, and the two manual forms; a record typed by a person is marked as such and can be removed

import { useState } from 'react';
import ErrorAlert from '@/components/ErrorAlert';
import RoleWeekSummary from '@/components/RoleWeekSummary';
import LoadingSpinner from '@/components/LoadingSpinner';
import { useRoleSummary } from '@/hooks/useRoleSummary';
import { useRoles } from '@/hooks/useRoles';
import { periodBack, PERIOD_OPTIONS, type PeriodChoice } from '@/lib/role-share';
import { formatMinutes } from '@/lib/day-format';
import {
  ACT_KIND_OPTIONS,
  MANUAL_MARK,
  NO_ACTS_TEXT,
  NO_MINUTES_TEXT,
  actLine,
  actsSummary,
  targetShareLine,
} from '@/lib/role-format';

export interface RolesScreenProps {
  /** Mobile trims the type scale; the structure is identical. */
  compact?: boolean;
}

/** Shown while the directory has not arrived and no form can be filled in. */
export const EMPTY_ROLES_TEXT =
  'Справочник ролей пуст: примените миграцию — четыре роли приезжают с ней.';

/** Label of the manual-minutes form, and of the act form under it. */
export const MINUTES_FORM_TITLE = 'Записать минуты';
export const ACT_FORM_TITLE = 'Записать акт роли';

/** Default number in the minutes field: an hour and a half, the canonical case. */
const DEFAULT_MINUTES = '90';

/**
 * Today's roles: where the minutes went, and whether a role happened at all.
 *
 * One component for both shells. Two measures, side by side and never folded
 * into one another — the share answers «куда ушёл день», the acts answer
 * «случилась ли роль», and a day of eight hours of review with one
 * architectural act has to read as both at once.
 */
export default function RolesScreen({ compact = false }: RolesScreenProps) {
  const { day, roles, loading, saving, error, addTimeBlock, addAct, deleteTimeBlock } =
    useRoles();

  // Период сводки выбирается человеком: тот же расчёт отвечает и за неделю, и
  // за месяц, поэтому выбор здесь — это выбор границ, а не другой запрос.
  const [period, setPeriod] = useState<PeriodChoice>('week');
  const range = day === null ? null : periodBack(day.work_day, period);
  const { summary } = useRoleSummary(range?.from ?? null, range?.to ?? null);

  const [minutesRole, setMinutesRole] = useState('');
  const [minutes, setMinutes] = useState(DEFAULT_MINUTES);
  const [minutesNote, setMinutesNote] = useState('');
  const [actRole, setActRole] = useState('');
  const [actKind, setActKind] = useState(ACT_KIND_OPTIONS[0]?.value ?? '');
  const [actTitle, setActTitle] = useState('');

  if (loading) return <LoadingSpinner />;
  if (!day || roles.length === 0)
    return (
      <div className="space-y-4">
        {error && <ErrorAlert message={error} />}
        <p className="text-text-secondary">{EMPTY_ROLES_TEXT}</p>
      </div>
    );

  const card = `bg-card border border-white/5 rounded-3xl ${compact ? 'p-4' : 'p-6'}`;
  const field =
    'w-full bg-background border border-white/10 rounded-xl px-3 py-2 text-sm text-text-primary';
  // The first role of the directory is what an unfilled picker means; the
  // directory is ordered so that is `cto`.
  const fallbackRole = roles[0].code;

  const submitMinutes = (event: React.FormEvent) => {
    event.preventDefault();
    void addTimeBlock({
      role_code: minutesRole || fallbackRole,
      minutes: Number(minutes),
      work_day: day.work_day,
      note: minutesNote || null,
    });
    setMinutesNote('');
  };

  const submitAct = (event: React.FormEvent) => {
    event.preventDefault();
    if (!actTitle.trim()) return;
    void addAct({
      role_code: actRole || fallbackRole,
      act_kind: actKind,
      title: actTitle.trim(),
      work_day: day.work_day,
    });
    setActTitle('');
  };

  return (
    <div className={compact ? 'space-y-4' : 'space-y-6'}>
      {error && <ErrorAlert message={error} />}

      {summary !== null && (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2">
            {PERIOD_OPTIONS.map((option) => (
              <button
                key={option.id}
                type="button"
                onClick={() => setPeriod(option.id)}
                className={`rounded-2xl px-3 py-1 text-sm ${
                  period === option.id
                    ? 'bg-lime text-background'
                    : 'bg-surface text-text-secondary'
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
          <RoleWeekSummary summary={summary} />
        </div>
      )}

      <section className={card}>
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="text-text-primary text-lg">Роли · {day.work_day}</h2>
          <span className="text-xs text-text-secondary">
            всего {formatMinutes(day.total_minutes)}
          </span>
        </div>
        <p className="text-sm text-text-secondary mt-1">{actsSummary(day)}</p>

        {day.total_minutes === 0 ? (
          <p className="text-sm text-text-secondary mt-4">{NO_MINUTES_TEXT}</p>
        ) : (
          <ul className="space-y-3 mt-4">
            {day.roles.map((slice) => {
              const target = targetShareLine(slice);
              return (
                <li key={slice.role_code}>
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="text-text-primary">{slice.title}</span>
                    <span className="text-sm text-text-secondary">
                      {formatMinutes(slice.minutes)} · {slice.share_pct}%
                    </span>
                  </div>
                  <div
                    aria-hidden="true"
                    className="h-1.5 mt-1 rounded-full bg-white/5 overflow-hidden"
                  >
                    <div
                      className="h-full bg-lime"
                      style={{ width: `${slice.share_pct}%` }}
                    />
                  </div>
                  {target && <p className="text-xs text-text-secondary mt-1">{target}</p>}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section className={card}>
        <h2 className="text-text-primary text-lg mb-3">Акты дня</h2>
        {day.acts.length === 0 ? (
          <p className="text-sm text-text-secondary">{NO_ACTS_TEXT}</p>
        ) : (
          <ul className="space-y-2">
            {day.acts.map((act) => (
              <li key={act.id} className="text-sm text-text-primary">
                {actLine(act)}
                {act.is_manual && (
                  <span className="text-xs text-text-secondary"> · {MANUAL_MARK}</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className={card}>
        <h2 className="text-text-primary text-lg mb-3">{MINUTES_FORM_TITLE}</h2>
        <form onSubmit={submitMinutes} className="space-y-2">
          <label className="block text-xs text-text-secondary" htmlFor="minutes-role">
            Роль
          </label>
          <select
            id="minutes-role"
            className={field}
            value={minutesRole || fallbackRole}
            onChange={(event) => setMinutesRole(event.target.value)}
          >
            {roles.map((role) => (
              <option key={role.code} value={role.code}>
                {role.title}
              </option>
            ))}
          </select>

          <label className="block text-xs text-text-secondary" htmlFor="minutes-value">
            Минуты
          </label>
          <input
            id="minutes-value"
            className={field}
            type="number"
            inputMode="numeric"
            value={minutes}
            onChange={(event) => setMinutes(event.target.value)}
          />

          <label className="block text-xs text-text-secondary" htmlFor="minutes-note">
            Чем занимался
          </label>
          <input
            id="minutes-note"
            className={field}
            type="text"
            placeholder="найм"
            value={minutesNote}
            onChange={(event) => setMinutesNote(event.target.value)}
          />

          <button
            type="submit"
            disabled={saving}
            className="text-sm px-4 py-2 rounded-xl bg-lime text-background disabled:opacity-50"
          >
            Записать
          </button>
        </form>

        {day.blocks.length > 0 && (
          <ul className="space-y-2 mt-4">
            {day.blocks.map((block) => (
              <li
                key={block.id}
                className="flex items-baseline justify-between gap-3 text-sm"
              >
                <span className="text-text-primary min-w-0">
                  {formatMinutes(block.minutes)} · {block.role_code}
                  {block.note ? ` · ${block.note}` : ''}
                  {block.is_manual && (
                    <span className="text-xs text-text-secondary"> · {MANUAL_MARK}</span>
                  )}
                </span>
                <button
                  type="button"
                  disabled={saving}
                  onClick={() => void deleteTimeBlock(block.id)}
                  className="text-xs px-2 py-1 rounded-xl border border-white/10 text-text-secondary disabled:opacity-50"
                >
                  убрать
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className={card}>
        <h2 className="text-text-primary text-lg mb-3">{ACT_FORM_TITLE}</h2>
        <form onSubmit={submitAct} className="space-y-2">
          <label className="block text-xs text-text-secondary" htmlFor="act-role">
            Роль
          </label>
          <select
            id="act-role"
            className={field}
            value={actRole || fallbackRole}
            onChange={(event) => setActRole(event.target.value)}
          >
            {roles.map((role) => (
              <option key={role.code} value={role.code}>
                {role.title}
              </option>
            ))}
          </select>

          <label className="block text-xs text-text-secondary" htmlFor="act-kind">
            Вид акта
          </label>
          <select
            id="act-kind"
            className={field}
            value={actKind}
            onChange={(event) => setActKind(event.target.value)}
          >
            {ACT_KIND_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>

          <label className="block text-xs text-text-secondary" htmlFor="act-title">
            Что это было
          </label>
          <input
            id="act-title"
            className={field}
            type="text"
            placeholder="ADR-0020"
            value={actTitle}
            onChange={(event) => setActTitle(event.target.value)}
          />

          <button
            type="submit"
            disabled={saving}
            className="text-sm px-4 py-2 rounded-xl bg-lime text-background disabled:opacity-50"
          >
            Записать акт
          </button>
        </form>
      </section>
    </div>
  );
}
