'use client';
// [review:need-review] PHASE-02/65, PHASE-03/209, PHASE-03/132
// summary: the sync-lag block sits above the catalog; mobile Health catalog — markup only; the fetch and the catalog body now come from useHealthMetrics/HealthMetricGroups, shared with the desktop /health screen so the two shells cannot disagree on a number

import LoadingSpinner from '@/components/LoadingSpinner';
import HealthMetricGroups from '@/components/health/HealthMetricGroups';
import HealthSyncStatus from '@/components/HealthSyncStatus';
import { useHealthMetrics } from '@/hooks/useHealthMetrics';
import { useHealthSyncStatus } from '@/hooks/useHealthSyncStatus';

export default function HealthPage() {
  const state = useHealthMetrics();
  const syncStatus = useHealthSyncStatus();

  return (
    <div className="space-y-5">
      <HealthSyncStatus status={syncStatus} />
      {state.status === 'loading' && <LoadingSpinner size="lg" />}
      {state.status === 'error' && <p className="text-sm text-danger">{state.message}</p>}
      {state.status === 'ready' && <HealthMetricGroups metrics={state.metrics} />}
    </div>
  );
}
