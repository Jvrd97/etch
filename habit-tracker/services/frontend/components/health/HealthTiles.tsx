// [review:need-review] PHASE-03/303
// summary: the steps and energy tiles of the Health screen — the latest number, the 30-day mean beside it and a lightweight SVG sparkline with a gap kept as a gap; a metric the catalog does not hold is left out, one without a day prints an honest line instead of a zero

import Link from 'next/link';
import type { HealthMetric } from '@/lib/api';
import { dayLabel, metricHref, SPARKLINE_DAYS, unitLabel } from '@/lib/health';
import { localDate } from '@/lib/health-metrics';
import {
  ENERGY_IDENTIFIER,
  HEALTH_COLORS,
  STEPS_IDENTIFIER,
  findMetric,
  tileSeries,
} from '@/lib/health-visual';
import { sparklineSegments, type TrendPoint } from '@/lib/trends';

const SPARK_WIDTH = 160;
const SPARK_HEIGHT = 40;
const SPARK_STROKE_PX = 2;
const COORDINATE_DECIMALS = 1;

const TILES: ReadonlyArray<{ identifier: string; title: string }> = [
  { identifier: STEPS_IDENTIFIER, title: 'Шаги' },
  { identifier: ENERGY_IDENTIFIER, title: 'Энергия' },
];

const grouped = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 });

/** `M x y L x y …` for one run of days; a lone day is `h0`, which a round cap turns into a dot. */
function pathData(segment: Array<{ x: number; y: number }>): string {
  const at = (point: { x: number; y: number }) =>
    `${point.x.toFixed(COORDINATE_DECIMALS)} ${point.y.toFixed(COORDINATE_DECIMALS)}`;
  const [first, ...rest] = segment;
  return rest.length === 0 ? `M${at(first)} h0` : `M${at(first)} ${rest.map((p) => `L${at(p)}`).join(' ')}`;
}

/** Decorative: the tile's text already says the number and the mean. */
function Spark({ points, color }: { points: TrendPoint[]; color: string }) {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      viewBox={`0 0 ${SPARK_WIDTH} ${SPARK_HEIGHT}`}
      preserveAspectRatio="none"
      overflow="visible"
      className="h-10 w-full"
    >
      {sparklineSegments(points, SPARK_WIDTH, SPARK_HEIGHT).map((segment) => (
        <path
          key={segment[0].x}
          d={pathData(segment)}
          fill="none"
          stroke={color}
          strokeWidth={SPARK_STROKE_PX}
          strokeLinecap="round"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
      ))}
    </svg>
  );
}

function HealthTile({
  metric,
  title,
  basePath,
}: {
  metric: HealthMetric;
  title: string;
  basePath: string;
}) {
  const { latest, average, points } = tileSeries(metric);
  const color = metric.identifier === STEPS_IDENTIFIER ? HEALTH_COLORS.lime : HEALTH_COLORS.sky;
  return (
    <Link
      href={metricHref(basePath, metric.identifier)}
      className="block min-h-11 rounded-3xl border border-white/5 bg-card p-4"
    >
      <h3 className="text-sm font-semibold text-text-secondary">{title}</h3>
      {latest === null ? (
        <p className="mt-2 text-sm text-text-secondary">Пока нет данных</p>
      ) : (
        <>
          <p className="mt-1 text-2xl font-semibold tabular-nums text-text-primary">
            {grouped.format(latest.value)}
            <span className="ml-1 text-sm font-normal text-text-secondary">
              {unitLabel(metric.identifier, metric.canonical_unit)}
            </span>
          </p>
          <p className="text-xs text-text-secondary">
            {latest.date === localDate() ? 'сегодня' : dayLabel(latest.date)}
            {average !== null &&
              ` · в среднем ${grouped.format(average)} за ${SPARKLINE_DAYS} дн.`}
          </p>
          <div className="mt-2">
            <Spark points={points} color={color} />
          </div>
        </>
      )}
    </Link>
  );
}

export interface HealthTilesProps {
  metrics: readonly HealthMetric[];
  basePath: string;
}

export default function HealthTiles({ metrics, basePath }: HealthTilesProps) {
  const present = TILES.flatMap(({ identifier, title }) => {
    const metric = findMetric(metrics, identifier);
    return metric === undefined ? [] : [{ metric, title }];
  });
  if (present.length === 0) return null;
  return (
    <div className="grid grid-cols-2 gap-3">
      {present.map(({ metric, title }) => (
        <HealthTile key={metric.identifier} metric={metric} title={title} basePath={basePath} />
      ))}
    </div>
  );
}
