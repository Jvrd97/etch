'use client';
// [review:need-review] PHASE-01/207
// summary: relapse block of an avoid category page — current and best streak, last relapse, relapse days in the last 7 and 30 days, average gap, trend against the month before, the history chart, the weekday split and the list of the latest relapse days

import { useId, useMemo } from 'react';
import { Flame, Minus, TrendingDown, TrendingUp } from 'lucide-react';
import type { RelapseHistory } from '@/lib/api';
import RelapseChart from '@/components/RelapseChart';
import { todayISO } from '@/lib/date';
import {
  MONTH_DAYS,
  WEEKDAY_LABELS,
  WEEK_DAYS,
  formatDayCount,
  formatGap,
  formatRelapseDay,
  formatWeekday,
  summarizeRelapses,
  type RelapseTrend,
} from '@/lib/relapse-analysis';

/** How many of the latest relapse days the list spells out. */
const RECENT_RELAPSES_SHOWN = 10;
/** The span the trend needs before it can compare a month with the one before. */
const TREND_HISTORY_DAYS = MONTH_DAYS * 2;

interface RelapseHistoryCardProps {
  history: RelapseHistory;
  /** Today as `YYYY-MM-DD`; injectable so tests pin the windows. */
  today?: string;
}

function TrendLine({ trend }: { trend: RelapseTrend }) {
  if (trend.kind === 'not-enough-data') {
    return (
      <p className="text-sm text-text-secondary">
        Тренд появится, когда история охватит {TREND_HISTORY_DAYS} дней.
      </p>
    );
  }
  const { current, previous } = trend;
  if (trend.kind === 'fewer') {
    return (
      <p className="flex items-center gap-2 text-sm text-success">
        <TrendingDown className="w-4 h-4" strokeWidth={2} aria-hidden="true" />
        {`Реже, чем месяц назад: ${current} против ${previous}`}
      </p>
    );
  }
  if (trend.kind === 'more') {
    return (
      <p className="flex items-center gap-2 text-sm text-danger">
        <TrendingUp className="w-4 h-4" strokeWidth={2} aria-hidden="true" />
        {`Чаще, чем месяц назад: ${current} против ${previous}`}
      </p>
    );
  }
  return (
    <p className="flex items-center gap-2 text-sm text-text-secondary">
      <Minus className="w-4 h-4" strokeWidth={2} aria-hidden="true" />
      {`Так же, как месяц назад: ${current}`}
    </p>
  );
}

export default function RelapseHistoryCard({ history, today }: RelapseHistoryCardProps) {
  const titleId = useId();
  const day = today ?? todayISO();
  const summary = useMemo(
    () => summarizeRelapses(history.relapse_dates, history.tracked_since, day),
    [history.relapse_dates, history.tracked_since, day]
  );
  const recent = history.relapse_dates.slice(-RECENT_RELAPSES_SHOWN).reverse();
  const busiestWeekday = Math.max(1, ...summary.weekdays);

  const stats: Array<[string, string]> = [
    ['Текущая серия', formatDayCount(history.current_streak)],
    ['Лучшая серия', formatDayCount(history.best_streak)],
    [
      'Последний срыв',
      history.last_relapse_date === null ? 'не было' : formatRelapseDay(history.last_relapse_date),
    ],
    [`Срывов за ${WEEK_DAYS} дней`, String(summary.lastWeek)],
    [`Срывов за ${MONTH_DAYS} дней`, String(summary.lastMonth)],
    ['Средний промежуток', summary.averageGapDays === null ? '—' : formatGap(summary.averageGapDays)],
  ];

  return (
    <section aria-labelledby={titleId} className="bg-card border border-white/5 rounded-3xl p-6 space-y-6">
      <div className="flex items-center gap-3">
        <div className="p-2.5 rounded-2xl bg-lime/10">
          <Flame className="w-5 h-5 text-lime" strokeWidth={2} aria-hidden="true" />
        </div>
        <h2 id={titleId} className="text-lg font-medium text-text-primary">
          Срывы
        </h2>
      </div>

      <dl className="grid grid-cols-2 sm:grid-cols-3 gap-5">
        {stats.map(([label, value]) => (
          <div key={label}>
            <dt className="text-[13px] font-medium text-text-secondary mb-1">{label}</dt>
            <dd className="text-2xl font-bold text-text-primary tracking-tight tabular-nums">{value}</dd>
          </div>
        ))}
      </dl>
      <p className="text-xs text-text-secondary">
        Срыв считается по дням: несколько за один день — один день со срывом.
      </p>

      <TrendLine trend={summary.trend} />

      <RelapseChart
        relapseDates={history.relapse_dates}
        trackedSince={history.tracked_since}
        today={day}
      />

      <div className="grid gap-6 sm:grid-cols-2">
        <div>
          <h3 className="text-sm font-medium text-text-primary mb-3">
            По дням недели
          </h3>
          <ul aria-label="Срывы по дням недели" className="space-y-2">
            {WEEKDAY_LABELS.map((label, index) => {
              const count = summary.weekdays[index];
              return (
                <li key={label} aria-label={`${label}: ${count}`} className="flex items-center gap-3 text-sm">
                  <span className="w-6 text-text-secondary" aria-hidden="true">
                    {label}
                  </span>
                  <span className="flex-1 h-2 rounded-full bg-surface" aria-hidden="true">
                    <span
                      className="block h-2 rounded-full bg-danger"
                      style={{ width: `${(count / busiestWeekday) * 100}%` }}
                    />
                  </span>
                  <span className="w-6 text-right tabular-nums text-text-primary" aria-hidden="true">
                    {count}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>

        <div>
          <h3 className="text-sm font-medium text-text-primary mb-3">Последние срывы</h3>
          {recent.length === 0 ? (
            <p className="text-sm text-text-secondary">Срывов не было</p>
          ) : (
            <ol aria-label="Последние срывы" className="space-y-1.5 text-sm text-text-primary">
              {recent.map((date) => (
                <li key={date}>{`${formatRelapseDay(date)}, ${formatWeekday(date)}`}</li>
              ))}
            </ol>
          )}
        </div>
      </div>
    </section>
  );
}
