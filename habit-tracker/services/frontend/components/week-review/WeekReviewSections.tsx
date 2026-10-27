// [review:need-review] PHASE-03/221, PHASE-03/239
// summary: the blocks of the week review — totals against the previous week, the seven days with the best and the worst marked in words, role and category time, avoid streaks, and the three health figures; every change is printed with its sign so no colour carries meaning alone

import type { ReactNode } from 'react';
import type {
  WeekReview,
  WeekReviewDay,
  WeekReviewHealth,
} from '@/lib/api';
import { countable } from '@/lib/plural';
import {
  METRIC_MISSING_TEXT,
  NOT_CLOSED,
  NO_DATA,
  deltaCount,
  deltaMinutes,
  deltaPoints,
  formatHealthDelta,
  formatHealthValue,
  formatMinutes,
  rolesNote,
  shortDate,
  trendOf,
  verdictLine,
  weekdayShort,
  type Trend,
} from '@/lib/week-review';

const TREND_CLASS: Record<Trend, string> = {
  up: 'text-lime',
  down: 'text-danger',
  flat: 'text-text-secondary',
};

const CARD = 'bg-card border border-white/5 rounded-3xl';

function Section({ label, title, children }: { label: string; title: string; children: ReactNode }) {
  return (
    <section aria-label={label} className="space-y-3">
      <h2 className="text-xl font-semibold text-text-primary">{title}</h2>
      {children}
    </section>
  );
}

/** A change against the previous week; the sign is the text, the colour only repeats it. */
function Change({ text, delta }: { text: string | null; delta: number | null }) {
  if (text === null) return <span className="text-text-disabled">—</span>;
  return <span className={TREND_CLASS[trendOf(delta)]}>{text}</span>;
}

function Stat({
  label,
  value,
  hint,
  change,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  change: ReactNode;
}) {
  return (
    <div className={`${CARD} p-4 min-w-0`}>
      <dt className="text-sm text-text-secondary">{label}</dt>
      <dd className="mt-1 text-2xl font-bold text-text-primary tabular-nums">
        {value}
        {hint !== undefined && <span className="text-sm text-text-secondary"> {hint}</span>}
      </dd>
      <dd className="mt-1 text-sm">{change}</dd>
    </div>
  );
}

export function TotalsBlock({ review }: { review: WeekReview }) {
  const { totals, delta, previous_totals: before } = review;
  return (
    <Section label="Итог недели" title="Итог недели">
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat
          label="Выиграно дней"
          value={totals.won_days}
          hint={`из ${totals.closed_days}`}
          change={
            <>
              <Change text={deltaCount(delta.won_days)} delta={delta.won_days} />
              <span className="text-text-disabled"> · было {before.won_days}</span>
            </>
          }
        />
        <Stat
          label="План"
          value={totals.plan_pct === null ? '—' : `${totals.plan_pct}%`}
          hint={`${totals.tasks_done} из ${totals.tasks_total}`}
          change={<Change text={deltaPoints(delta.plan_pct)} delta={delta.plan_pct} />}
        />
        <Stat
          label="Рабочее время"
          value={totals.work_minutes === null ? '—' : formatMinutes(totals.work_minutes)}
          change={
            <Change text={deltaMinutes(delta.work_minutes)} delta={delta.work_minutes} />
          }
        />
        <Stat
          label="Серия дней"
          value={totals.day_streak_end === null ? '—' : totals.day_streak_end}
          hint={totals.day_streak_end === null ? undefined : 'на конец'}
          change={
            <span className="text-text-secondary">
              {totals.anchors_total > 0
                ? `Якоря: ${totals.anchors_done} из ${totals.anchors_total}`
                : 'Якорей не было'}
            </span>
          }
        />
      </dl>
      <p className="text-sm text-text-secondary">{verdictLine(review)}</p>
    </Section>
  );
}

/** Full word for screen readers and the tooltip; the cell itself prints the short form. */
function dayCaption(day: WeekReviewDay): { full: string; short: string } {
  if (!day.counted) return { full: 'не учтён', short: '—' };
  if (day.verdict === 'won') return { full: 'выигран', short: 'выигр.' };
  if (day.verdict === 'lost') return { full: 'проигран', short: 'проигр.' };
  return { full: NOT_CLOSED, short: 'открыт' };
}

function DayCell({ day, mark }: { day: WeekReviewDay; mark: string | null }) {
  const caption = dayCaption(day);
  const tone =
    day.verdict === 'won'
      ? 'border-lime/60'
      : day.verdict === 'lost'
        ? 'border-danger/50'
        : 'border-white/10';
  return (
    <li
      className={`flex min-w-0 flex-col items-center gap-1 rounded-2xl border bg-card px-1 py-2 text-center ${tone}`}
    >
      <span className="text-xs text-text-disabled">{weekdayShort(day.weekday)}</span>
      <span className="text-xs text-text-secondary tabular-nums">{shortDate(day.date)}</span>
      <span className="text-[11px] leading-tight text-text-primary" title={caption.full}>
        <span aria-hidden="true">{caption.short}</span>
        <span className="sr-only">{caption.full}</span>
      </span>
      <span className="text-xs text-text-secondary tabular-nums">
        {day.counted && day.tasks_total > 0 ? `${day.tasks_done}/${day.tasks_total}` : '·'}
      </span>
      <span className="min-h-4 text-[11px] font-medium leading-tight text-lime">{mark ?? ''}</span>
    </li>
  );
}

export function DaysBlock({ review }: { review: WeekReview }) {
  return (
    <Section label="Дни недели" title="Дни">
      <ul className="grid grid-cols-7 gap-1.5 sm:gap-2">
        {review.days.map((day) => (
          <DayCell
            key={day.date}
            day={day}
            mark={
              day.date === review.best_day
                ? 'лучший'
                : day.date === review.worst_day
                  ? 'худший'
                  : null
            }
          />
        ))}
      </ul>
      {review.best_day === null && (
        <p className="text-sm text-text-disabled">Закрытых дней пока нет: лучшего и худшего нет.</p>
      )}
    </Section>
  );
}

export function RolesBlock({ review }: { review: WeekReview }) {
  const rows = review.roles.filter((role) => role.minutes > 0 || role.previous_minutes > 0);
  const note = rolesNote(review.window);
  return (
    <Section label="Время по ролям" title="Время по ролям">
      {rows.length === 0 ? (
        <p className="text-text-disabled">Минуты по ролям не записаны.</p>
      ) : (
        <ul className={`${CARD} overflow-hidden`}>
          {rows.map((role) => (
            <li
              key={role.role_id}
              className="flex min-h-14 items-center justify-between gap-3 border-b border-white/5 px-4 py-3 last:border-b-0"
            >
              <span className="min-w-0 break-words text-sm text-text-primary">{role.title}</span>
              <span className="shrink-0 text-right text-sm tabular-nums text-text-secondary">
                {formatMinutes(role.minutes)} · {role.share_pct}%
                <br />
                <Change text={deltaMinutes(role.delta_minutes)} delta={role.delta_minutes} />
              </span>
            </li>
          ))}
        </ul>
      )}
      {rows.length > 0 && note !== null && <p className="text-sm text-text-disabled">{note}</p>}
    </Section>
  );
}

export function CategoriesBlock({ review }: { review: WeekReview }) {
  return (
    <Section label="Время по категориям" title="Время по категориям">
      {review.categories.length === 0 ? (
        <p className="text-text-disabled">Записей со временем нет.</p>
      ) : (
        <ul className={`${CARD} overflow-hidden`}>
          {review.categories.map((category) => (
            <li
              key={category.category_id}
              className="flex min-h-14 items-center justify-between gap-3 border-b border-white/5 px-4 py-3 last:border-b-0"
            >
              <span className="min-w-0 break-words text-sm text-text-primary">
                {category.name}
                <span className="block text-xs text-text-disabled">
                  {countable(category.entry_days, 'день', 'дня', 'дней')} с записью
                </span>
              </span>
              <span className="shrink-0 text-right text-sm tabular-nums text-text-secondary">
                {formatMinutes(category.minutes)}
                <br />
                <Change
                  text={deltaMinutes(category.delta_minutes)}
                  delta={category.delta_minutes}
                />
              </span>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

export function StreaksBlock({ review }: { review: WeekReview }) {
  return (
    <Section label="Серии привычек" title="Серии привычек">
      {review.habit_streaks.length === 0 ? (
        <p className="text-text-disabled">Привычек «избегать» с историей нет.</p>
      ) : (
        <ul className={`${CARD} overflow-hidden`}>
          {review.habit_streaks.map((streak) => (
            <li
              key={streak.category_id}
              className="flex min-h-14 items-center justify-between gap-3 border-b border-white/5 px-4 py-3 last:border-b-0"
            >
              <span className="min-w-0 break-words text-sm text-text-primary">{streak.name}</span>
              <span className="shrink-0 text-right text-sm tabular-nums text-text-secondary">
                {countable(streak.current_streak, 'день', 'дня', 'дней')}
                <br />
                <span className={streak.relapses > 0 ? 'text-danger' : 'text-text-disabled'}>
                  {streak.relapses > 0
                    ? `${countable(streak.relapses, 'срыв', 'срыва', 'срывов')} за неделю`
                    : 'без срывов'}
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

function HealthCard({ metric }: { metric: WeekReviewHealth }) {
  const average = metric.avg_per_day;
  return (
    <div className={`${CARD} p-4 min-w-0`}>
      <dt className="text-sm text-text-secondary">{metric.name}</dt>
      {!metric.available ? (
        <dd className="mt-1 text-sm text-text-disabled">{METRIC_MISSING_TEXT}</dd>
      ) : average === null ? (
        <dd className="mt-1 text-sm text-text-disabled">{NO_DATA}</dd>
      ) : (
        <>
          <dd className="mt-1 text-2xl font-bold text-text-primary tabular-nums">
            {formatHealthValue(metric.unit, average)}
            <span className="text-sm text-text-secondary"> в день</span>
          </dd>
          <dd className="mt-1 text-sm">
            <Change text={formatHealthDelta(metric)} delta={metric.delta_avg_per_day} />
            <span className="text-text-disabled">
              {' '}
              · {countable(metric.days_with_data, 'день', 'дня', 'дней')} с данными
            </span>
          </dd>
        </>
      )}
    </div>
  );
}

export function HealthBlock({ review }: { review: WeekReview }) {
  return (
    <Section label="Здоровье" title="Здоровье">
      <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {review.health.map((metric) => (
          <HealthCard key={metric.key} metric={metric} />
        ))}
      </dl>
    </Section>
  );
}
