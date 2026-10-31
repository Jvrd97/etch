'use client';
// [review:need-review] PHASE-02/65, PHASE-03/209, PHASE-03/132, PHASE-03/238, PHASE-02/68, PHASE-02/70, PHASE-02/69, PHASE-03/303
// summary: the visual blocks (state of the day, steps and energy tiles, sleep by night, deviation bars, 30-day workouts) sit under the sync block and above the catalog; the sync-lag block sits above them; mobile Health catalog — markup only; the fetch and the catalog body now come from useHealthMetrics/HealthMetricGroups, shared with the desktop /health screen so the two shells cannot disagree on a number

import LoadingSpinner from '@/components/LoadingSpinner';
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
    <div className="space-y-5">
      <HealthSyncStatus status={syncStatus} />
      <HealthVisuals
        score={score}
        metrics={state.status === 'ready' ? state.metrics : null}
        nights={sleepNights}
        workouts={workouts}
        basePath="/m/health"
        sleepDetailHref={metricHref('/m/health', SLEEP_IDENTIFIER)}
      />
      {state.status === 'loading' && <LoadingSpinner size="lg" />}
      {state.status === 'error' && <p className="text-sm text-danger">{state.message}</p>}
      {state.status === 'ready' && <HealthMetricGroups metrics={state.metrics} basePath="/m/health" />}
    </div>
  );
}
