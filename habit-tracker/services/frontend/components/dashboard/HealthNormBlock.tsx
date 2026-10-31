// [review:need-review] #302
// summary: sleep, resting pulse and the other Health metrics of the window with their distance from the personal norm - signed value, an arrow and a word, so the direction does not depend on colour; no norm yet says so

import { Minus, TrendingDown, TrendingUp } from 'lucide-react';
import type { DashboardHealthMetric } from '@/lib/api';
import {
  deltaTone,
  formatDelta,
  formatMetricValue,
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
  const tone = deltaTone(metric.identifier, delta);
  const Icon = delta === null || delta === 0 ? Minus : delta > 0 ? TrendingUp : TrendingDown;
  const text =
    delta === null || delta === 0
      ? formatDelta(delta, metric.unit)
      : `${formatDelta(delta, metric.unit)} от вашей нормы`;
  return (
    <span className={`flex items-center gap-1.5 text-[13px] ${TONE_CLASS[tone]}`}>
      <Icon className="h-4 w-4" strokeWidth={2} aria-hidden="true" />
      {text}
    </span>
  );
}

interface HealthNormBlockProps {
  metrics: DashboardHealthMetric[];
  mobile?: boolean;
}

export function HealthNormBlock({ metrics, mobile = false }: HealthNormBlockProps) {
  return (
    <DashboardCard title="Сон и пульс покоя" aside="среднее за период" mobile={mobile}>
      {metrics.length === 0 ? (
        <EmptyLine>Данных мало: сон и пульс придут из Apple Health.</EmptyLine>
      ) : (
        <ul className="divide-y divide-white/5">
          {metrics.map((metric) => (
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
