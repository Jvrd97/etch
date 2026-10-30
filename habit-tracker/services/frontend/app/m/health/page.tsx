'use client';
// [review:need-review] PHASE-02/65, PHASE-03/209, PHASE-03/132, PHASE-03/238, PHASE-02/68, PHASE-02/70
// summary: the workouts section (week of workouts as events) sits under the sleep section; the sleep section (last night, stages, week of nights) sits under the sync block; the sync-lag block sits above the catalog; mobile Health catalog — markup only; the fetch and the catalog body now come from useHealthMetrics/HealthMetricGroups, shared with the desktop /health screen so the two shells cannot disagree on a number

import LoadingSpinner from '@/components/LoadingSpinner';
import HealthMetricGroups from '@/components/health/HealthMetricGroups';
import HealthSyncStatus from '@/components/HealthSyncStatus';
import SleepSection from '@/components/health/SleepSection';
import { useSleepNights } from '@/components/health/useSleepNights';
import WorkoutsSection from '@/components/health/WorkoutsSection';
import { useWorkouts } from '@/components/health/useWorkouts';
import { useHealthMetrics } from '@/hooks/useHealthMetrics';
import { useHealthSyncStatus } from '@/hooks/useHealthSyncStatus';

export default function HealthPage() {
  const state = useHealthMetrics();
  const syncStatus = useHealthSyncStatus();
  const sleepNights = useSleepNights();
  const workouts = useWorkouts();

  return (
    <div className="space-y-5">
      <HealthSyncStatus status={syncStatus} />
      <SleepSection nights={sleepNights} />
      <WorkoutsSection workouts={workouts} />
      {state.status === 'loading' && <LoadingSpinner size="lg" />}
      {state.status === 'error' && <p className="text-sm text-danger">{state.message}</p>}
      {state.status === 'ready' && <HealthMetricGroups metrics={state.metrics} basePath="/m/health" />}
    </div>
  );
}
