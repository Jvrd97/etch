'use client';
// [review:need-review] PHASE-03/86, PHASE-03/87
// summary: desktop day screen — date, kind of day, the plan in sections with the day's schedule and its collisions, an explicit "плана нет" when there is none, and the rule this particular day is judged by

import { CalendarCheck, CodeXml, Moon, Sun } from 'lucide-react';
import DaySchedule from '@/components/day/DaySchedule';
import ErrorAlert from '@/components/ErrorAlert';
import LoadingSpinner from '@/components/LoadingSpinner';
import PlanSections from '@/components/day/PlanSections';
import { useDay } from '@/hooks/useDay';
import {
  NO_PLAN_HINT,
  NO_PLAN_TEXT,
  dayKindLabel,
  ruleLines,
  ruleValidity,
} from '@/lib/day-format';
import { countTasks, overlappingItemIds } from '@/lib/plan';

/** `date` is null on the entry point `/day`, where the server names today. */
export interface DayScreenProps {
  date: string | null;
}

export default function DayScreen({ date }: DayScreenProps) {
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

  const { day, rule, plan } = detail;
  const KindIcon = day.kind === 'work' ? Sun : Moon;

  return (
    <div className="space-y-8 animate-fade-rise">
      <div>
        <h1 className="text-4xl font-bold text-text-primary tracking-tight">
          {day.date}
          <span className="text-lime">.</span>
        </h1>
        <div className="mt-3 flex flex-wrap items-center gap-3 text-text-secondary">
          <span className="inline-flex items-center gap-2">
            <KindIcon className="w-4 h-4" strokeWidth={2} />
            {dayKindLabel(day)}
          </span>
          {day.is_nocode && (
            <span className="inline-flex items-center gap-2 px-3 py-1 rounded-2xl bg-surface text-sm">
              <CodeXml className="w-4 h-4" strokeWidth={2} />
              no-code day
            </span>
          )}
        </div>
      </div>

      {plan === null ? (
        <div className="bg-card border border-white/5 rounded-3xl text-center py-16 px-6">
          <div className="inline-flex p-4 rounded-3xl bg-surface mb-4">
            <CalendarCheck className="w-8 h-8 text-text-disabled" strokeWidth={2} />
          </div>
          <p className="text-text-primary text-lg font-medium">{NO_PLAN_TEXT}</p>
          <p className="mt-2 text-text-secondary max-w-md mx-auto">{NO_PLAN_HINT}</p>
        </div>
      ) : (
        <>
          {plan.lede && (
            <p className="text-text-secondary max-w-3xl">{plan.lede}</p>
          )}
          <p className="text-sm text-text-secondary">
            Рабочих задач: {countTasks(plan)} из {rule.max_work_tasks}
          </p>
          <DaySchedule schedule={plan.schedule} overlaps={plan.overlaps} />
          <PlanSections
            sections={plan.sections}
            overlapping={overlappingItemIds(plan.overlaps)}
          />
        </>
      )}

      <section className="bg-card border border-white/5 rounded-3xl p-6">
        <h2 className="text-xl font-semibold text-text-primary">
          По какому правилу считается этот день
        </h2>
        <p className="mt-1 text-sm text-text-secondary">{ruleValidity(rule)}</p>

        <dl className="mt-5 grid gap-x-8 gap-y-3 sm:grid-cols-2">
          {ruleLines(rule).map((line) => (
            <div key={line.label} className="flex justify-between gap-4">
              <dt className="text-text-secondary">{line.label}</dt>
              <dd className="text-text-primary text-right">{line.value}</dd>
            </div>
          ))}
        </dl>

        {rule.note_md && (
          <p className="mt-5 pt-5 border-t border-white/5 text-sm text-text-secondary">
            {rule.note_md}
          </p>
        )}
      </section>
    </div>
  );
}
