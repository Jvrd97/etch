'use client';
// [review:need-review] PHASE-03/86, PHASE-03/87, PHASE-03/90, PHASE-03/91, PHASE-03/143
// summary: mobile day screen — markup only, all state comes from useDay and useDayMarks (shared with the desktop shell); one column, the plan with its schedule and marks in compact form, the итог with the verdict, the notebook, the rule as a plain list, no text below text-sm

import { useMemo } from 'react';
import { CalendarCheck, CodeXml, Moon, Sun } from 'lucide-react';
import DayNotebook from '@/components/day/DayNotebook';
import DaySchedule from '@/components/day/DaySchedule';
import DayVerdict from '@/components/day/DayVerdict';
import WorkIntervals from '@/components/day/WorkIntervals';
import ErrorAlert from '@/components/ErrorAlert';
import LoadingSpinner from '@/components/LoadingSpinner';
import PlanSections from '@/components/day/PlanSections';
import { useDay } from '@/hooks/useDay';
import { useDayMarks } from '@/hooks/useDayMarks';
import { useWorkIntervals } from '@/hooks/useWorkIntervals';
import {
  dayAPI,
  type DayCloseDraft,
  type DayReviewDraft,
  type Mark,
  type WorkDay,
} from '@/lib/api';
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

/**
 * Stable empty work block for a day that has not loaded yet.
 *
 * `work_minutes: null` is the honest value for it: «не измерено», not zero.
 */
const NO_WORK: WorkDay = {
  day_date: '',
  intervals: [],
  work_minutes: null,
  running: false,
};

/** `date` is null on the entry point `/m/day`, where the server names today. */
export interface MobileDayScreenProps {
  date: string | null;
}

export default function MobileDayScreen({ date }: MobileDayScreenProps) {
  // `true`: a person is looking at this day, which is what fills `opened_at`.
  const { detail, loading, error, reload } = useDay(date, true);
  const marks = useMemo(() => detail?.marks ?? NO_MARKS, [detail]);
  const kinds = useMemo(() => itemKindsById(detail?.plan ?? null), [detail]);
  const marking = useDayMarks(detail?.day.date ?? '', marks, kinds);
  const work = useMemo(() => detail?.work ?? NO_WORK, [detail]);
  const intervals = useWorkIntervals(detail?.day.date ?? '', work);

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
          {day.opened_at === null && (
            <span className="px-3 py-1 rounded-2xl bg-surface">
              {DAY_NEVER_OPENED}
            </span>
          )}
        </div>
      </div>

      {plan === null ? (
        <div className="bg-card border border-white/5 rounded-3xl text-center py-10 px-5">
          <div className="inline-flex p-3 rounded-3xl bg-surface mb-3">
            <CalendarCheck className="w-7 h-7 text-text-disabled" strokeWidth={2} />
          </div>
          <p className="text-text-primary font-medium">{NO_PLAN_TEXT}</p>
          <p className="mt-2 text-sm text-text-secondary">{NO_PLAN_HINT}</p>
        </div>
      ) : (
        <>
          {plan.lede && (
            <p className="text-sm text-text-secondary">{plan.lede}</p>
          )}
          <p className="text-sm text-text-secondary">
            Рабочих задач: {marking.counts.planned} из {rule.max_work_tasks} ·{' '}
            {taskCountsLine(marking.counts)}
          </p>
          {marking.error && (
            <ErrorAlert message={marking.error} onDismiss={() => reload()} />
          )}
          <DaySchedule schedule={plan.schedule} overlaps={plan.overlaps} compact />
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
            compact
          />
        </>
      )}

      <WorkIntervals
        work={intervals.work}
        saving={intervals.saving}
        error={intervals.error}
        onAdd={async (started_at, ended_at) => {
          await intervals.add({ started_at, ended_at });
          // The verdict of the day stands on this sum, so the day is re-read
          // rather than only the block that changed.
          reload();
        }}
        onStop={async (id, ended_at) => {
          await intervals.edit(id, { ended_at });
          reload();
        }}
        onRemove={async (id) => {
          await intervals.remove(id);
          reload();
        }}
        compact
      />

      <DayVerdict
        summary={detail.summary}
        onReview={async (draft: DayReviewDraft) => {
          await dayAPI.review(day.date, draft);
          // Ревью двигает стадию и рабочие минуты, а счётчики дня остаются
          // живыми: перечитываем день целиком, как и после закрытия.
          reload();
        }}
        onClose={async (draft: DayCloseDraft) => {
          await dayAPI.closeFinal(day.date, draft);
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
        compact
      />

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
