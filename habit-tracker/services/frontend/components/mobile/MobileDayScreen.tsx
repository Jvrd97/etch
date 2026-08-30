'use client';
// [review:need-review] PHASE-03/86
// summary: mobile day screen — markup only, all state comes from useDay (shared with the desktop shell); one column, the rule as a plain list, no text below text-sm

import { CalendarCheck, CodeXml, Moon, Sun } from 'lucide-react';
import ErrorAlert from '@/components/ErrorAlert';
import LoadingSpinner from '@/components/LoadingSpinner';
import { useDay } from '@/hooks/useDay';
import {
  NO_PLAN_HINT,
  NO_PLAN_TEXT,
  dayKindLabel,
  ruleLines,
  ruleValidity,
} from '@/lib/day-format';

/** `date` is null on the entry point `/m/day`, where the server names today. */
export interface MobileDayScreenProps {
  date: string | null;
}

export default function MobileDayScreen({ date }: MobileDayScreenProps) {
  const { detail, loading, error, reload } = useDay(date);

  if (loading) return <LoadingSpinner size="lg" />;
  if (error || detail === null) {
    return (
      <ErrorAlert
        message={error ?? 'День не загрузился'}
        onDismiss={() => reload()}
      />
    );
  }

  const { day, rule } = detail;
  const KindIcon = day.kind === 'work' ? Sun : Moon;

  return (
    <div className="space-y-5 animate-fade-rise">
      <div className="bg-card border border-white/5 rounded-3xl p-4">
        <p className="text-2xl font-bold text-text-primary tracking-tight">
          {day.date}
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-3 text-sm text-text-secondary">
          <span className="inline-flex items-center gap-2">
            <KindIcon className="w-4 h-4" strokeWidth={2} />
            {dayKindLabel(day)}
          </span>
          {day.is_nocode && (
            <span className="inline-flex items-center gap-2 px-3 py-1 rounded-2xl bg-surface">
              <CodeXml className="w-4 h-4" strokeWidth={2} />
              no-code day
            </span>
          )}
        </div>
      </div>

      {!detail.has_plan && (
        <div className="bg-card border border-white/5 rounded-3xl text-center py-10 px-5">
          <div className="inline-flex p-3 rounded-3xl bg-surface mb-3">
            <CalendarCheck className="w-7 h-7 text-text-disabled" strokeWidth={2} />
          </div>
          <p className="text-text-primary font-medium">{NO_PLAN_TEXT}</p>
          <p className="mt-2 text-sm text-text-secondary">{NO_PLAN_HINT}</p>
        </div>
      )}

      <section className="bg-card border border-white/5 rounded-3xl p-4">
        <h2 className="text-base font-semibold text-text-primary">
          По какому правилу считается этот день
        </h2>
        <p className="mt-1 text-sm text-text-secondary">{ruleValidity(rule)}</p>

        <dl className="mt-4 space-y-2.5">
          {ruleLines(rule).map((line) => (
            <div key={line.label} className="flex justify-between gap-4 text-sm">
              <dt className="text-text-secondary">{line.label}</dt>
              <dd className="text-text-primary text-right">{line.value}</dd>
            </div>
          ))}
        </dl>

        {rule.note_md && (
          <p className="mt-4 pt-4 border-t border-white/5 text-sm text-text-secondary">
            {rule.note_md}
          </p>
        )}
      </section>
    </div>
  );
}
