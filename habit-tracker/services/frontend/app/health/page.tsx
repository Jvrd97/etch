'use client';
// [review:need-review] PHASE-03/209
// summary: desktop /health screen — same catalog, same numbers as /m/health, through the shared useHealthMetrics hook and HealthMetricGroups body; only the page frame (title, loading, error) is drawn twice, as every other desktop/mobile pair in this app does

import LoadingSpinner from '@/components/LoadingSpinner';
import ErrorAlert from '@/components/ErrorAlert';
import HealthMetricGroups from '@/components/health/HealthMetricGroups';
import { useHealthMetrics } from '@/hooks/useHealthMetrics';

export default function HealthPage() {
  const state = useHealthMetrics();

  return (
    <div className="space-y-8 animate-fade-rise">
      <div>
        <h1 className="text-4xl font-bold text-text-primary tracking-tight">
          Health
          <span className="text-lime">.</span>
        </h1>
        <p className="mt-2 text-text-secondary">
          Каталог метрик с телефона: сегодняшние числа по группам.
        </p>
      </div>

      {state.status === 'loading' && <LoadingSpinner size="lg" />}
      {state.status === 'error' && <ErrorAlert message={state.message} />}
      {state.status === 'ready' && <HealthMetricGroups metrics={state.metrics} />}
    </div>
  );
}
