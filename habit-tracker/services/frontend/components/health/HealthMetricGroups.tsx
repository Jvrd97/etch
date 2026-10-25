// [review:need-review] PHASE-03/209
// summary: the catalog body both /health and /m/health render — the Apple access link, each group's rows with a value or "Нет данных", and the whole-catalog empty state; identical markup is the point, since the two screens show the same numbers

import type { HealthMetric } from '@/lib/api';
import {
  HEALTH_ACCESS_LABEL,
  HEALTH_ACCESS_URL,
  HEALTH_GROUPS,
  HEALTH_SYNC_HINT,
  isCatalogEmpty,
} from '@/lib/health-metrics';

export interface HealthMetricGroupsProps {
  metrics: HealthMetric[];
}

export default function HealthMetricGroups({ metrics }: HealthMetricGroupsProps) {
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
                <HealthMetricRow key={metric.identifier} metric={metric} />
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

function HealthMetricRow({ metric }: { metric: HealthMetric }) {
  const latest = metric.days.at(-1);
  return (
    <div className="flex min-h-14 items-center justify-between gap-4 border-b border-white/5 px-4 py-3 last:border-b-0">
      <span className="text-sm text-text-primary">{metric.display_name}</span>
      <span className="text-right text-sm tabular-nums text-text-secondary">
        {latest === undefined ? 'Нет данных' : `${latest.value} ${metric.canonical_unit}`}
      </span>
    </div>
  );
}
