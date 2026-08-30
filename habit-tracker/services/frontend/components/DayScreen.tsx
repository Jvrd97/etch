'use client';
// [review:need-review] PHASE-03/86, PHASE-03/87, PHASE-03/90, PHASE-03/94
// summary: desktop day screen — date, kind of day, the plan in sections with its schedule, its collisions and its marks, the итог with the verdict and the condition it failed on, the notebook of the day, an explicit "плана нет" when there is none, the rule this particular day is judged by, and the shared day navigation beside it

import { useMemo } from 'react';
import { CalendarCheck, CodeXml, Moon, Sun } from 'lucide-react';
import DayNotebook from '@/components/day/DayNotebook';
import DaySidebar from '@/components/day/DaySidebar';
import DaySchedule from '@/components/day/DaySchedule';
import DayVerdict from '@/components/day/DayVerdict';
import ErrorAlert from '@/components/ErrorAlert';
import LoadingSpinner from '@/components/LoadingSpinner';
import PlanSections from '@/components/day/PlanSections';
import { useDay } from '@/hooks/useDay';
import { useDayMarks } from '@/hooks/useDayMarks';
import { dayAPI, type DayCloseDraft, type Mark } from '@/lib/api';
import {
  NO_PLAN_HINT,
  NO_PLAN_TEXT,
  dayKindLabel,
  ruleLines,
  ruleValidity,
} from '@/lib/day-format';
import { DAY_NEVER_OPENED, taskCountsLine } from '@/lib/marks';
import { itemKindsById, overlappingItemIds } from '@/lib/plan';

/**
 * Stable empty list for a day that has not loaded yet.
 *
 * A fresh `[]` on every render would look like new marks to `useDayMarks` and
 * put the screen in a loop.
 */
const NO_MARKS: Mark[] = [];

/** `date` is null on the entry point `/day`, where the server names today. */
export interface DayScreenProps {
  date: string | null;
}

export default function DayScreen({ date }: DayScreenProps) {
  // `true`: a person is looking at this day, which is what fills `opened_at`.
  const { detail, loading, error, reload } = useDay(date, true);
  const marks = useMemo(() => detail?.marks ?? NO_MARKS, [detail]);
  const kinds = useMemo(() => itemKindsById(detail?.plan ?? null), [detail]);
  const marking = useDayMarks(detail?.day.date ?? '', marks, kinds);

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
    <div className="lg:grid lg:grid-cols-[16rem_1fr] lg:gap-8">
      {/* The same navigation `/life` draws, so the two screens cannot drift. */}
      <aside className="hidden lg:block">
        <DaySidebar activeDate={day.date} />
      </aside>
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
          {day.opened_at === null && (
            <span className="px-3 py-1 rounded-2xl bg-surface text-sm">
              {DAY_NEVER_OPENED}
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
            Рабочих задач: {marking.counts.planned} из {rule.max_work_tasks} ·{' '}
            {taskCountsLine(marking.counts)}
          </p>
          {marking.error && (
            <ErrorAlert message={marking.error} onDismiss={() => reload()} />
          )}
          <DaySchedule schedule={plan.schedule} overlaps={plan.overlaps} />
          <PlanSections
            sections={plan.sections}
            overlapping={overlappingItemIds(plan.overlaps)}
            marking={{
              marks: marking.marks,
              saving: marking.saving,
              onCycle: marking.cycle,
              onSetState: marking.setState,
              onSetNote: marking.setNote,
            }}
          />
        </>
      )}

      <DayVerdict
        summary={detail.summary}
        onClose={async (draft: DayCloseDraft) => {
          await dayAPI.close(day.date, draft);
          // Re-read rather than patch in place: closing re-folds the streak of
          // every later day, so the server's answer is the only correct one.
          reload();
        }}
      />

      <DayNotebook
        value={detail.notebook}
        onSave={async (content) => {
          await dayAPI.saveNotebook(day.date, content);
        }}
      />

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
    </div>
  );
}
