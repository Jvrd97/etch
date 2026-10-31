// [review:need-review] #302
// summary: the dashboard layout from a summary state - header with the window and the period switch, then the seven blocks in one grid (two columns on a desktop, one on a phone); loading is a skeleton, an error is a Russian alert with «Повторить», a period switch dims the old numbers while the new ones load

import { AlertCircle, RotateCcw } from 'lucide-react';
import type { DashboardPeriod } from '@/lib/api';
import type { DashboardSummaryState } from '@/hooks/useDashboardSummary';
import { formatDayShort, formatRange } from '@/lib/dashboard-summary';
import { TAP_TARGET_PX } from '@/lib/ui-constants';
import { BestsBlock } from './BestsBlock';
import { HealthNormBlock } from './HealthNormBlock';
import { InsightBlock } from './InsightBlock';
import { NutritionSoonBlock } from './NutritionSoonBlock';
import { PeriodSwitch } from './PeriodSwitch';
import { ScoreRings } from './ScoreRings';
import { StreaksBlock } from './StreaksBlock';
import { WorkoutsBlock } from './WorkoutsBlock';

const SKELETON_BLOCKS = 4;

interface DashboardViewProps {
  state: DashboardSummaryState;
  period: DashboardPeriod;
  onPeriodChange: (period: DashboardPeriod) => void;
  onRetry: () => void;
  mobile?: boolean;
}

function Skeleton({ mobile }: { mobile: boolean }) {
  return (
    <div role="status" aria-label="Загружаем сводку" className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      {Array.from({ length: SKELETON_BLOCKS }, (_, index) => (
        <div
          key={index}
          aria-hidden="true"
          className={`rounded-3xl border border-white/5 bg-card motion-safe:animate-pulse ${
            mobile ? 'h-40' : 'h-56'
          }`}
        />
      ))}
    </div>
  );
}

function ErrorPanel({ message, onRetry, mobile }: { message: string; onRetry: () => void; mobile: boolean }) {
  return (
    <div
      role="alert"
      className="flex flex-col gap-4 rounded-3xl border border-danger/40 bg-surface p-5 sm:flex-row sm:items-center"
    >
      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-2xl bg-danger/10">
        <AlertCircle className="h-5 w-5 text-danger" strokeWidth={2} aria-hidden="true" />
      </span>
      <p className="flex-1 text-sm text-text-primary">{message}</p>
      <button
        type="button"
        onClick={onRetry}
        style={mobile ? { minHeight: TAP_TARGET_PX } : undefined}
        className="inline-flex items-center justify-center gap-2 rounded-2xl border border-lime/40 px-5 py-2.5 font-medium text-lime transition-colors duration-200 hover:bg-lime/10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-lime"
      >
        <RotateCcw className="h-4 w-4" strokeWidth={2} aria-hidden="true" />
        Повторить
      </button>
    </div>
  );
}

export function DashboardView({
  state,
  period,
  onPeriodChange,
  onRetry,
  mobile = false,
}: DashboardViewProps) {
  const summary = state.status === 'ready' ? state.summary : null;
  return (
    <div className="space-y-6 animate-fade-rise">
      <header
        className={`flex gap-4 ${mobile ? 'flex-col' : 'flex-row items-end justify-between'}`}
      >
        <div>
          <h1
            className={
              mobile ? 'sr-only' : 'text-4xl font-bold tracking-tight text-text-primary'
            }
          >
            Дашборд
            {!mobile && <span className="text-lime">.</span>}
          </h1>
          <p className="mt-1 text-text-secondary" aria-live="polite">
            {summary === null
              ? state.status === 'error'
                ? 'Сводка недоступна'
                : 'Собираем сводку…'
              : `${formatRange(summary.from, summary.to)} · сегодня ${formatDayShort(summary.today)}`}
          </p>
        </div>
        <PeriodSwitch period={period} onChange={onPeriodChange} mobile={mobile} />
      </header>

      {state.status === 'ready' && state.refreshFailed && !state.refreshing && (
        <p role="status" className="text-[13px] text-warning">
          Не удалось обновить сводку, показаны прежние данные.
        </p>
      )}

      {state.status === 'loading' && <Skeleton mobile={mobile} />}
      {state.status === 'error' && (
        <ErrorPanel message={state.message} onRetry={onRetry} mobile={mobile} />
      )}
      {summary !== null && (
        <div
          aria-busy={state.status === 'ready' && state.refreshing}
          className={`grid grid-cols-1 gap-6 transition-opacity duration-200 lg:grid-cols-2 ${
            state.status === 'ready' && state.refreshing ? 'opacity-60' : ''
          }`}
        >
          <ScoreRings scores={summary.scores} mobile={mobile} />
          <HealthNormBlock metrics={summary.health} mobile={mobile} />
          <StreaksBlock streaks={summary.streaks} mobile={mobile} />
          <BestsBlock bests={summary.bests} period={summary.period} mobile={mobile} />
          <WorkoutsBlock workouts={summary.workouts} mobile={mobile} />
          <InsightBlock insight={summary.insight} period={summary.period} mobile={mobile} />
          <NutritionSoonBlock mobile={mobile} />
        </div>
      )}
    </div>
  );
}
