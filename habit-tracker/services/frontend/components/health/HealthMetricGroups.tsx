// [review:need-review] PHASE-03/209, PHASE-02/68, PHASE-02/69
// summary: the catalog body both /health and /m/health render — the Apple access link, each group's rows with the latest value, a 30-day sparkline and the deviation from the metric's own baseline (or "Нет данных"), and the whole-catalog empty state; identical markup is the point, since the two screens show the same numbers

import Link from 'next/link';
import type { HealthMetric } from '@/lib/api';
import { TrendSparkline } from '@/components/dashboard/TrendSparkline';
import { dayLabel, deviationText, formatValue, metricHref, OUTSIDE_TYPICAL_TEXT, sparklinePoints } from '@/lib/health';
import {
  HEALTH_ACCESS_LABEL,
  HEALTH_ACCESS_URL,
  HEALTH_GROUPS,
  HEALTH_SYNC_HINT,
  isCatalogEmpty,
  localDate,
} from '@/lib/health-metrics';

export interface HealthMetricGroupsProps {
  metrics: HealthMetric[];
  /** `/health` on the desktop, `/m/health` on the phone: where a row's detail screen lives. */
  basePath: string;
}

export default function HealthMetricGroups({ metrics, basePath }: HealthMetricGroupsProps) {
  if (isCatalogEmpty(metrics)) {
    return (
      <div className="space-y-5 animate-fade-rise">
        <HealthAccessLink />
        <p role="status" className="text-sm text-text-secondary">
          {HEALTH_SYNC_HINT}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-5 animate-fade-rise">
      <HealthAccessLink />

      {HEALTH_GROUPS.map((group) => (
        <section key={group.id} aria-labelledby={`health-${group.id}`}>
          <h2
            id={`health-${group.id}`}
            className="mb-2 text-sm font-semibold text-text-secondary"
          >
            {group.title}
          </h2>
          <div className="overflow-hidden rounded-3xl border border-white/5 bg-card">
            {metrics
              .filter((metric) => metric.group === group.id)
              .map((metric) => (
                <HealthMetricRow key={metric.identifier} metric={metric} basePath={basePath} />
              ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function HealthAccessLink() {
  return (
    <a
      href={HEALTH_ACCESS_URL}
      target="_blank"
      rel="noreferrer"
      className="inline-flex min-h-11 items-center text-sm font-medium text-lime"
    >
      {HEALTH_ACCESS_LABEL}
    </a>
  );
}

function HealthMetricRow({ metric, basePath }: { metric: HealthMetric; basePath: string }) {
  const latest = metric.days.at(-1);
  const { baseline } = metric;
  return (
    <Link
      href={metricHref(basePath, metric.identifier)}
      className="flex min-h-14 items-center justify-between gap-4 border-b border-white/5 px-4 py-3 last:border-b-0"
    >
      <span className="text-sm text-text-primary">{metric.display_name}</span>
      <span className="flex items-center gap-3">
        <span className="text-text-secondary">
          <TrendSparkline
            points={latest === undefined ? [] : sparklinePoints(metric.days, latest.date)}
            color="currentColor"
          />
        </span>
        <span className="text-right text-sm tabular-nums text-text-secondary">
          {latest === undefined ? (
            'Нет данных'
          ) : (
            <>
              {`${formatValue(latest.value)} ${metric.canonical_unit}`}
              {latest.date !== localDate() && (
                <span className="block text-xs">{dayLabel(latest.date)}</span>
              )}
              {baseline !== null && (
                <span
                  className={`block text-xs ${baseline.outside_typical ? 'text-lime' : ''}`}
                >
                  {baseline.day !== latest.date && `${dayLabel(baseline.day)}: `}
                  {deviationText(baseline, metric.canonical_unit)}
                  {baseline.outside_typical && `, ${OUTSIDE_TYPICAL_TEXT}`}
                </span>
              )}
            </>
          )}
        </span>
      </span>
    </Link>
  );
}
