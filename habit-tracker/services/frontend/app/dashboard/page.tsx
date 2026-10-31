'use client';
// [review:need-review] #302
// summary: desktop Dashboard - the summary screen of the approved mockup (rings, streaks, health against the norm, bests, workouts, insight of the week, nutrition placeholder) read from GET /dashboard/summary

import { DashboardView } from '@/components/dashboard/DashboardView';
import { useDashboardSummary } from '@/hooks/useDashboardSummary';

export default function Dashboard() {
  const { state, period, setPeriod, reload } = useDashboardSummary();
  return (
    <DashboardView state={state} period={period} onPeriodChange={setPeriod} onRetry={reload} />
  );
}
