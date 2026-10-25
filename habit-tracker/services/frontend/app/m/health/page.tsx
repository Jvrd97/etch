'use client';
// [review:need-review] PHASE-02/65, PHASE-03/209
// summary: mobile Health catalog — markup only; the fetch and the catalog body now come from useHealthMetrics/HealthMetricGroups, shared with the desktop /health screen so the two shells cannot disagree on a number

import LoadingSpinner from '@/components/LoadingSpinner';
import HealthMetricGroups from '@/components/health/HealthMetricGroups';
import { useHealthMetrics } from '@/hooks/useHealthMetrics';

export default function HealthPage() {
  const state = useHealthMetrics();

  if (state.status === 'loading') return <LoadingSpinner size="lg" />;
  if (state.status === 'error') {
    return <p className="text-sm text-danger">{state.message}</p>;
  }

  return <HealthMetricGroups metrics={state.metrics} />;
}
