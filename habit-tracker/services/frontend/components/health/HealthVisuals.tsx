// [review:need-review] PHASE-03/303
// summary: the visual part of /health and /m/health in one place so the two shells cannot lay it out differently — the day's state card with the steps and energy tiles, sleep by night beside the deviation bars, the 30-day workouts; each block hides itself without its data, the catalog list stays below it on the page

import type { HealthScore, HealthSleepNight, HealthWorkout, HealthMetric } from '@/lib/api';
import { isCatalogEmpty } from '@/lib/health-metrics';
import DeviationBars from './DeviationBars';
import HealthStateCard from './HealthStateCard';
import HealthTiles from './HealthTiles';
import SleepNightsChart from './SleepNightsChart';
import WorkoutsSection from './WorkoutsSection';

export interface HealthVisualsProps {
  score: HealthScore | null;
  /** Null while the catalog loads or after a failed read. */
  metrics: HealthMetric[] | null;
  nights: HealthSleepNight[] | null;
  workouts: HealthWorkout[] | null;
  /** `/health` or `/m/health`: where the tiles and the sleep link lead. */
  basePath: string;
  sleepDetailHref: string;
}

export default function HealthVisuals({
  score,
  metrics,
  nights,
  workouts,
  basePath,
  sleepDetailHref,
}: HealthVisualsProps) {
  const catalog = metrics !== null && !isCatalogEmpty(metrics) ? metrics : null;

  return (
    <div className="space-y-4">
      {(score !== null || catalog !== null) && (
        <div
          className={`grid gap-4 ${score !== null && catalog !== null ? 'lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]' : ''}`}
        >
          <HealthStateCard score={score} />
          {catalog !== null && <HealthTiles metrics={catalog} basePath={basePath} />}
        </div>
      )}
      <div className="grid items-start gap-4 lg:grid-cols-2">
        <SleepNightsChart nights={nights} detailHref={sleepDetailHref} />
        {catalog !== null && <DeviationBars metrics={catalog} />}
      </div>
      <WorkoutsSection workouts={workouts} />
    </div>
  );
}
