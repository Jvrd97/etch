'use client';
// [review:need-review] PHASE-02/65
// summary: mobile Health catalog grouped by the server, with values, honest empty states, and access instructions

import { useEffect, useState } from 'react';
import { healthAPI, type HealthMetric, type HealthMetricGroup } from '@/lib/api';

const APPLE_ACCESS_INSTRUCTIONS =
  'https://support.apple.com/guide/iphone/share-health-and-fitness-data-iph5ede58c3d/ios';

const GROUPS: ReadonlyArray<{ id: HealthMetricGroup; title: string }> = [
  { id: 'movement', title: 'Движение и энергия' },
  { id: 'heart', title: 'Сердце и дыхание' },
  { id: 'body', title: 'Тело' },
  { id: 'nutrition', title: 'Питание' },
];

function localDate(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export default function HealthPage() {
  const [metrics, setMetrics] = useState<HealthMetric[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const today = localDate();
    void healthAPI
      .getMetrics(today, today)
      .then((response) => setMetrics(response.metrics))
      .catch(() => setError('Не удалось загрузить данные здоровья'));
  }, []);

  if (error !== null) {
    return <p className="text-sm text-danger">{error}</p>;
  }
  if (metrics === null) {
    return <p className="text-sm text-text-secondary">Загрузка…</p>;
  }

  return (
    <div className="space-y-5 animate-fade-rise">
      <a
        href={APPLE_ACCESS_INSTRUCTIONS}
        target="_blank"
        rel="noreferrer"
        className="inline-flex min-h-11 items-center text-sm font-medium text-lime"
      >
        Настройки доступа
      </a>

      {GROUPS.map((group) => (
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
                <MetricRow key={metric.identifier} metric={metric} />
              ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function MetricRow({ metric }: { metric: HealthMetric }) {
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
