'use client';
// [review:need-review] PHASE-03/147, PHASE-03/148
// summary: the «плана нет» card with the way out of it — one button that asks the model for the day, the waiting said out loud while the model thinks, the refusal said in words rather than left as a dead button, and the canon-only skeleton offered the moment generation fails; one component for both shells, so the mobile screen cannot drift from the desktop one

import { CalendarCheck } from 'lucide-react';
import ErrorAlert from '@/components/ErrorAlert';
import { usePlanBuild } from '@/hooks/usePlanBuild';
import { NO_PLAN_HINT, NO_PLAN_TEXT } from '@/lib/day-format';

/** The main way out of an empty day: ask the model. */
export const BUILD_PLAN_LABEL = 'Собрать план';

/** The same button after a failure — it says that the last attempt is over. */
export const BUILD_PLAN_RETRY_LABEL = 'Попробовать ещё раз';

/**
 * Said while the model is thinking.
 *
 * The seconds are named on purpose: a button that does nothing visible for six
 * seconds is a button a person presses twice.
 */
export const BUILD_PLAN_RUNNING = 'Собираю план — модель отвечает несколько секунд';

/** The fallback path, named by what it does without the model. */
export const BUILD_SKELETON_LABEL = 'Собрать из канона, без модели';

/** Said while the canon is being laid out; it takes no model and no waiting. */
export const BUILD_SKELETON_RUNNING = 'Собираю план из канона';

/**
 * What the fallback is, beside the button that runs it.
 *
 * Offered only after generation failed: the day is planned by the model by
 * default, and the skeleton is the promise that a silent model still leaves a
 * day with edges, a free evening and its anchors.
 */
export const BUILD_FALLBACK_HINT =
  'Модель не ответила. Скелет соберётся без неё — края дня, свободный вечер и якоря по правилу этого дня.';

export interface PlanBuilderProps {
  /** The day being planned. Always the server's date, never the browser's. */
  date: string;
  /** Re-read the day once a plan exists; this card then gives way to it. */
  onBuilt: () => void;
  compact?: boolean;
}

/**
 * The day without a plan, and the two ways to give it one.
 *
 * Before this card the empty day was a dead end: the screen said «плана нет»
 * and offered nothing, while both endpoints that build one had been on the
 * server for weeks. Saying what is missing without offering the thing that
 * fills it is the same as not saying it.
 */
export default function PlanBuilder({ date, onBuilt, compact = false }: PlanBuilderProps) {
  const { state, generate, buildSkeleton } = usePlanBuild(date, onBuilt);
  const running = state.status === 'generating' || state.status === 'skeleton';

  return (
    <div
      className={`bg-card border border-white/5 rounded-3xl text-center ${
        compact ? 'py-10 px-5' : 'py-16 px-6'
      }`}
    >
      <div className={`inline-flex rounded-3xl bg-surface ${compact ? 'p-3 mb-3' : 'p-4 mb-4'}`}>
        <CalendarCheck
          className={`text-text-disabled ${compact ? 'w-7 h-7' : 'w-8 h-8'}`}
          strokeWidth={2}
        />
      </div>
      <p className={`text-text-primary font-medium ${compact ? '' : 'text-lg'}`}>
        {NO_PLAN_TEXT}
      </p>
      <p
        className={`mt-2 text-text-secondary ${compact ? 'text-sm' : 'max-w-md mx-auto'}`}
      >
        {NO_PLAN_HINT}
      </p>

      <div className="mt-6 flex flex-col items-center gap-4">
        <button
          type="button"
          disabled={running}
          onClick={() => void generate()}
          className="text-sm px-5 py-2.5 rounded-xl bg-lime text-background font-medium disabled:opacity-50"
        >
          {state.status === 'failed' ? BUILD_PLAN_RETRY_LABEL : BUILD_PLAN_LABEL}
        </button>

        {running && (
          // `aria-live`, not a spinner alone: the wait is what the reader needs
          // told, and «идёт» has to reach a screen reader as words too.
          <p role="status" aria-live="polite" className="text-sm text-text-secondary animate-pulse">
            {state.status === 'generating' ? BUILD_PLAN_RUNNING : BUILD_SKELETON_RUNNING}
          </p>
        )}

        {state.status === 'failed' && (
          <div className="w-full max-w-md text-left space-y-3">
            <ErrorAlert message={state.message} />
            <p className="text-sm text-text-secondary">{BUILD_FALLBACK_HINT}</p>
            <button
              type="button"
              onClick={() => void buildSkeleton()}
              className="text-sm px-4 py-2 rounded-xl bg-surface text-text-secondary"
            >
              {BUILD_SKELETON_LABEL}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
