// [review:need-review] #302
// summary: «Состояние здоровья» - every key Health metric the server sent (up to five) with its distance from the personal norm: signed value, an arrow and the words «лучше нормы» / «хуже нормы», so the verdict does not depend on colour; the direction comes from the server's `higher_is_better`; no norm yet says so

import { Minus, TrendingDown, TrendingUp } from 'lucide-react';
import type { DashboardHealthMetric } from '@/lib/api';
import {
  deltaTone,
  formatDelta,
  formatMetricValue,
  TONE_WORDS,
  type DeltaTone,
} from '@/lib/dashboard-summary';
import { DashboardCard, EmptyLine } from './DashboardCard';

const TONE_CLASS: Record<DeltaTone, string> = {
  good: 'text-success',
  bad: 'text-danger',
  neutral: 'text-text-secondary',
};

function DeltaLine({ metric }: { metric: DashboardHealthMetric }) {
  const { baseline_delta: delta } = metric;
  const tone = deltaTone(metric.identifier, delta, metric.higher_is_better);
  const toneWord = TONE_WORDS[tone];
  const Icon = delta === null || delta === 0 ? Minus : delta > 0 ? TrendingUp : TrendingDown;
  const text =
    delta === null || delta === 0
      ? formatDelta(delta, metric.unit)
      : `${formatDelta(delta, metric.unit)} от вашей нормы`;
  return (
    <span className={`flex flex-col items-end text-[13px] ${TONE_CLASS[tone]}`}>
      <span className="flex items-center gap-1.5">
        <Icon className="h-4 w-4" strokeWidth={2} aria-hidden="true" />
        {text}
      </span>
      {toneWord !== null && <span className="text-[12px] font-medium">{toneWord}</span>}
    </span>
  );
}

/** The server lists the five key metrics; a longer list is cut rather than stretching the card. */
export const MAX_HEALTH_METRICS = 5;

interface HealthNormBlockProps {
  metrics: DashboardHealthMetric[];
  mobile?: boolean;
}

export function HealthNormBlock({ metrics, mobile = false }: HealthNormBlockProps) {
  return (
    <DashboardCard title="Состояние здоровья" aside="среднее за период" mobile={mobile}>
      {metrics.length === 0 ? (
        <EmptyLine>Данных мало: показатели здоровья придут из Apple Health.</EmptyLine>
      ) : (
        <ul className="divide-y divide-white/5">
          {metrics.slice(0, MAX_HEALTH_METRICS).map((metric) => (
            <li key={metric.identifier} className="flex items-center justify-between gap-4 py-3">
              <div className="min-w-0">
                <p className="text-[13px] text-text-secondary">{metric.label}</p>
                <p className={`font-bold text-text-primary ${mobile ? 'text-xl' : 'text-2xl'}`}>
                  {formatMetricValue(metric.value, metric.unit)}
                </p>
              </div>
              <DeltaLine metric={metric} />
            </li>
          ))}
        </ul>
      )}
    </DashboardCard>
  );
}
