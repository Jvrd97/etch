'use client';
// [review:need-review] #302
// summary: mobile Dashboard - the same summary screen as the desktop one, laid out in one column with 44 px targets

import { DashboardView } from '@/components/dashboard/DashboardView';
import { useDashboardSummary } from '@/hooks/useDashboardSummary';

export default function MobileDashboardPage() {
  const { state, period, setPeriod, reload } = useDashboardSummary();
  return (
    <DashboardView
      state={state}
      period={period}
      onPeriodChange={setPeriod}
      onRetry={reload}
      mobile
    />
  );
}
