'use client';
// [review:need-review] PHASE-03/94, PHASE-03/138
// summary: the week page (`/week/{iso}`, and the current week on the bare `/week`) — won days, the streak at its end and when the counters were taken, the seven day squares, the sunday checklist with its ticks, and the retro prose; a week nobody wrote about opens and says so instead of looking broken

import Link from 'next/link';
import ErrorAlert from '@/components/ErrorAlert';
import LoadingSpinner from '@/components/LoadingSpinner';
import Markdown from '@/components/Markdown';
import DaySquare from '@/components/life/DaySquare';
import RoleWeekSummary from '@/components/RoleWeekSummary';
import { useDays } from '@/hooks/useDays';
import { useRoleSummary } from '@/hooks/useRoleSummary';
import { LOAD_WEEK_ERROR, useWeek } from '@/hooks/useWeek';
import { dayStatus, daysByDate, toISODate, WEEKDAY_SHORT } from '@/lib/life';

/** Shown in place of the retro when nobody has written one. */
export const NO_RETRO_TEXT = 'Ретро не написано';

/**
 * Said under that. The week exists all the same — its days happened — and the
 * page has to make that the reading rather than looking like a failed load.
 */
export const NO_RETRO_HINT =
  'Разбор этой недели ещё не собран. Счётчики и дни ниже — уже есть.';

export interface WeekScreenProps {
  /** `null` on the bare `/week`, where the server names the current week. */
  iso: string | null;
  compact?: boolean;
  today?: Date;
}

export default function WeekScreen({ iso, compact = false, today = new Date() }: WeekScreenProps) {
  const { week, loading, error, reload } = useWeek(iso);
  const todayISO = toISODate(today);

  // The days are asked for by date rather than taken from the week: the week
  // row is a snapshot of counters, and the squares have to show the days as they
  // are now — that difference is the whole point of `computed_at`.
  const { days } = useDays(week?.starts_on ?? todayISO, week?.ends_on ?? todayISO);
  const byDate = daysByDate(days);
  // Сводка ролей за ту же неделю: числа пятничного отчёта живут там же, где
  // разбор недели, а не собираются отдельно перед его написанием.
  const { summary } = useRoleSummary(week?.starts_on ?? null, week?.ends_on ?? null);

  if (loading) return <LoadingSpinner size="lg" />;
  if (error !== null || week === null) {
    return <ErrorAlert message={error ?? LOAD_WEEK_ERROR} onDismiss={() => reload()} />;
  }

  const hasRetro = week.retro_md.trim().length > 0;

  return (
    <div className="space-y-8 animate-fade-rise">
      <header>
        <h1
          className={`${compact ? 'text-2xl' : 'text-4xl'} font-bold text-text-primary tracking-tight`}
        >
          {week.iso_code}
          <span className="text-lime">.</span>
        </h1>
        <p className="mt-2 text-text-secondary">
          {week.starts_on} — {week.ends_on}
        </p>
      </header>

      <dl className="grid grid-cols-2 sm:grid-cols-3 gap-4">
        <div className="bg-card border border-white/5 rounded-2xl p-4">
          <dt className="text-sm text-text-secondary">Выиграно дней</dt>
          <dd className="text-3xl font-bold text-lime">
            {week.won_days}
            <span className="text-sm text-text-secondary"> из {week.total_days}</span>
          </dd>
        </div>
        <div className="bg-card border border-white/5 rounded-2xl p-4">
          <dt className="text-sm text-text-secondary">Стрик на конец</dt>
          <dd className="text-3xl font-bold text-text-primary">
            {week.streak_end === null ? '—' : week.streak_end}
          </dd>
        </div>
        <div className="bg-card border border-white/5 rounded-2xl p-4">
          <dt className="text-sm text-text-secondary">Счётчики сняты</dt>
          <dd className="text-text-primary">{week.computed_at.slice(0, 16).replace('T', ' ')}</dd>
        </div>
      </dl>

      <section aria-label="Дни недели" className="grid grid-cols-7 gap-2">
        {WEEKDAY_SHORT.map((name, index) => {
          const date = shiftISO(week.starts_on, index);
          return (
            <div key={name} className="flex flex-col items-center gap-2">
              <span className="text-xs text-text-disabled">{name}</span>
              <DaySquare
                date={date}
                size="lg"
                status={dayStatus(byDate.get(date), date, todayISO)}
                detail={byDate.get(date)?.title}
                isToday={date === todayISO}
              />
            </div>
          );
        })}
      </section>

      <section aria-label="На разбор в воскресенье" className="space-y-3">
        <h2 className="text-xl font-semibold text-text-primary">На разбор в воскресенье</h2>
        {week.review_items.length === 0 ? (
          <p className="text-text-disabled">Вопросов на разбор не поставлено.</p>
        ) : (
          <ul className="space-y-2">
            {week.review_items.map((item) => (
              <li key={item.id} className="flex items-start gap-3">
                <span
                  aria-hidden="true"
                  className={`mt-1 w-4 h-4 shrink-0 rounded border ${
                    item.done ? 'bg-lime border-lime' : 'border-white/20'
                  }`}
                />
                <span className="sr-only">{item.done ? 'закрыт' : 'не закрыт'}</span>
                <div className="text-text-secondary">
                  <Markdown content={item.text_md} />
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {summary !== null && (
        // Сводка стоит перед ретро, а не после: числа пишутся в отчёт, и
        // читать их после написанного разбора поздно.
        <RoleWeekSummary summary={summary} title="Роли за неделю" />
      )}

      <section aria-label="Ретро недели" className="space-y-3">
        <h2 className="text-xl font-semibold text-text-primary">Ретро</h2>
        {hasRetro ? (
          <Markdown content={week.retro_md} />
        ) : (
          <div className="bg-card border border-white/5 rounded-3xl text-center py-12 px-6">
            <p className="text-text-primary text-lg font-medium">{NO_RETRO_TEXT}</p>
            <p className="mt-2 text-text-secondary">{NO_RETRO_HINT}</p>
          </div>
        )}
      </section>

      {week.blockers_md.trim().length > 0 && (
        <section aria-label="Что мешало" className="space-y-3">
          <h2 className="text-xl font-semibold text-text-primary">Что мешало</h2>
          <Markdown content={week.blockers_md} />
        </section>
      )}

      {week.mgmt_retro_md.trim().length > 0 && (
        <section aria-label="Mgmt-ретро" className="space-y-3">
          <h2 className="text-xl font-semibold text-text-primary">Mgmt-ретро</h2>
          <Markdown content={week.mgmt_retro_md} />
        </section>
      )}

      {week.weekly_number_md.trim().length > 0 && (
        <section aria-label="Недельное число" className="space-y-3">
          <h2 className="text-xl font-semibold text-text-primary">Недельное число</h2>
          <Markdown content={week.weekly_number_md} />
        </section>
      )}

      <Link href="/life" className="inline-block text-lime hover:underline">
        ← К таймлайну
      </Link>
    </div>
  );
}

/**
 * `starts_on` moved by whole days, without leaving the string form.
 *
 * The week's Monday comes off the API as `YYYY-MM-DD`; parsing it into a Date
 * and back would be one more place a timezone could shift a square by a day.
 */
function shiftISO(from: string, days: number): string {
  const [year, month, day] = from.split('-').map(Number);
  const moved = new Date(year, month - 1, day + days);
  return toISODate(moved);
}
