// [review:need-review] PHASE-03/303
// summary: «Отклонение от вашей нормы» — a horizontal bar around a zero line for resting heart rate, HRV and breathing, each metric against its own baseline; the bar reaches the edge at two usual spreads, amber and the words «вне обычного» when the day sits beyond the usual spread; a metric with too little history gets a line instead of a bar

import type { HealthMetric } from '@/lib/api';
import { deviationText, formatQuantity, OUTSIDE_TYPICAL_TEXT } from '@/lib/health';
import { HEALTH_COLORS, deviationRows, type DeviationRow } from '@/lib/health-visual';

const HALF_TRACK_PERCENT = 50;

export const DEVIATION_NO_NORM_TEXT = 'Мало истории для нормы';

export interface DeviationBarsProps {
  metrics: readonly HealthMetric[];
}

export default function DeviationBars({ metrics }: DeviationBarsProps) {
  const rows = deviationRows(metrics);
  if (rows.length === 0) return null;

  return (
    <section
      aria-labelledby="health-deviation"
      className="rounded-3xl border border-white/5 bg-card p-5"
    >
      <h2 id="health-deviation" className="text-sm font-semibold text-text-secondary">
        Отклонение от вашей нормы
      </h2>
      <p className="text-xs text-text-secondary">
        Линия посередине — ваша обычная величина; край полосы — два обычных разброса.
      </p>
      <ul className="mt-4 space-y-4">
        {rows.map((row) => (
          <DeviationItem key={row.identifier} row={row} />
        ))}
      </ul>
    </section>
  );
}

function DeviationItem({ row }: { row: DeviationRow }) {
  const { metric, ratio, tone } = row;
  const { baseline } = metric;
  const color = tone === 'warn' ? HEALTH_COLORS.amber : HEALTH_COLORS.lime;
  const latest = metric.days.at(-1);

  return (
    <li>
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className="text-text-primary">{row.label}</span>
        <span className="text-right tabular-nums text-text-secondary">
          {latest !== undefined && formatQuantity(metric.identifier, latest.value, metric.canonical_unit)}
        </span>
      </div>
      <div
        aria-hidden="true"
        className="relative mt-1.5 h-2 rounded-full bg-white/10"
      >
        <span className="absolute inset-y-[-3px] left-1/2 w-px bg-white/40" />
        {ratio !== null && ratio !== 0 && (
          <span
            className="absolute inset-y-0 rounded-full"
            style={{
              backgroundColor: color,
              width: `${Math.abs(ratio) * HALF_TRACK_PERCENT}%`,
              ...(ratio > 0
                ? { left: `${HALF_TRACK_PERCENT}%` }
                : { right: `${HALF_TRACK_PERCENT}%` }),
            }}
          />
        )}
      </div>
      <p className="mt-1 text-xs text-text-secondary" style={tone === 'warn' ? { color } : undefined}>
        {baseline === null ? (
          DEVIATION_NO_NORM_TEXT
        ) : (
          <>
            {deviationText(baseline, metric.identifier, metric.canonical_unit)}
            {baseline.outside_typical && `, ${OUTSIDE_TYPICAL_TEXT}`}
          </>
        )}
      </p>
    </li>
  );
}
