'use client';
// [review:need-review] PHASE-03/209, PHASE-03/132, PHASE-03/238, PHASE-02/68, PHASE-02/70, PHASE-02/69, PHASE-03/303
// summary: the visual blocks (state of the day, steps and energy tiles, sleep by night, deviation bars, 30-day workouts) sit under the sync block and above the full catalog; the sync-lag block sits under the title; desktop /health screen — same catalog, same numbers as /m/health, through the shared useHealthMetrics hook and HealthMetricGroups body; only the page frame (title, loading, error) is drawn twice, as every other desktop/mobile pair in this app does

import LoadingSpinner from '@/components/LoadingSpinner';
import ErrorAlert from '@/components/ErrorAlert';
import HealthMetricGroups from '@/components/health/HealthMetricGroups';
import HealthSyncStatus from '@/components/HealthSyncStatus';
import HealthVisuals from '@/components/health/HealthVisuals';
import { useSleepNights } from '@/components/health/useSleepNights';
import { SLEEP_IDENTIFIER, metricHref } from '@/lib/health';
import { useWorkouts } from '@/components/health/useWorkouts';
import { useHealthMetrics } from '@/hooks/useHealthMetrics';
import { useHealthScore } from '@/hooks/useHealthScore';
import { useHealthSyncStatus } from '@/hooks/useHealthSyncStatus';

export default function HealthPage() {
  const state = useHealthMetrics();
  const syncStatus = useHealthSyncStatus();
  const sleepNights = useSleepNights();
  const workouts = useWorkouts();
  const score = useHealthScore();

  return (
    <div className="space-y-8 animate-fade-rise">
      <div>
        <h1 className="text-4xl font-bold text-text-primary tracking-tight">
          Health
          <span className="text-lime">.</span>
        </h1>
        <p className="mt-2 text-text-secondary">
          Состояние, сон и тренировки с телефона, ниже — все метрики по группам.
        </p>
      </div>

      <HealthSyncStatus status={syncStatus} />
      <HealthVisuals
        score={score}
        metrics={state.status === 'ready' ? state.metrics : null}
        nights={sleepNights}
        workouts={workouts}
        basePath="/health"
        sleepDetailHref={metricHref('/health', SLEEP_IDENTIFIER)}
      />

      {state.status === 'loading' && <LoadingSpinner size="lg" />}
      {state.status === 'error' && <ErrorAlert message={state.message} />}
      {state.status === 'ready' && <HealthMetricGroups metrics={state.metrics} basePath="/health" />}
    </div>
  );
}
