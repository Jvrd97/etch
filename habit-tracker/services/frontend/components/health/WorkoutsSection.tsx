// [review:need-review] PHASE-02/70
// summary: the workouts section both /health and /m/health render — the week's workouts as a list of events, newest first (type, day and start time on the phone's own clock, active time, then only the numbers HealthKit held: distance, energy, average and maximum heart rate); no chart, nothing before the answer, an honest line when none arrived

import type { HealthWorkout } from '@/lib/api';
import { nightLabel, sleepDuration, wallClock } from './SleepSection';

const METERS_PER_KILOMETER = 1000;
const FRACTION_DIGITS = 1;

export const WORKOUTS_EMPTY_TEXT =
  'Тренировок за неделю нет: они приходят с телефона вместе с остальными метриками.';

const number = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: FRACTION_DIGITS });

/** `7200` → `7,2 км`, `850` → `850 м`. */
export function workoutDistance(meters: number): string {
  return meters >= METERS_PER_KILOMETER
    ? `${number.format(meters / METERS_PER_KILOMETER)} км`
    : `${Math.round(meters)} м`;
}

/** The numbers HealthKit held for the workout, in reading order; a missing one is left out. */
export function workoutDetails(workout: HealthWorkout): string[] {
  const details: string[] = [];
  if (workout.distance_m !== null) details.push(workoutDistance(workout.distance_m));
  if (workout.energy_kcal !== null) details.push(`${Math.round(workout.energy_kcal)} ккал`);
  if (workout.avg_heart_rate !== null) {
    details.push(`пульс ${Math.round(workout.avg_heart_rate)} уд/мин`);
  }
  if (workout.max_heart_rate !== null) {
    details.push(`макс. ${Math.round(workout.max_heart_rate)}`);
  }
  return details;
}

export interface WorkoutsSectionProps {
  /** Oldest first; null while loading or after a failed read. */
  workouts: HealthWorkout[] | null;
}

export default function WorkoutsSection({ workouts }: WorkoutsSectionProps) {
  if (workouts === null) return null;

  const newestFirst = [...workouts].reverse();
  return (
    <section aria-labelledby="health-workouts" className="space-y-2">
      <h2 id="health-workouts" className="text-sm font-semibold text-text-secondary">
        Тренировки
      </h2>
      <div className="overflow-hidden rounded-3xl border border-white/5 bg-card">
        {newestFirst.length === 0 ? (
          <p role="status" className="px-4 py-3 text-sm text-text-secondary">
            {WORKOUTS_EMPTY_TEXT}
          </p>
        ) : (
          <ol aria-label="Тренировки недели" className="divide-y divide-white/5">
            {newestFirst.map((workout) => (
              <WorkoutRow key={workout.id} workout={workout} />
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}

function WorkoutRow({ workout }: { workout: HealthWorkout }) {
  const details = workoutDetails(workout);
  return (
    <li className="space-y-0.5 px-4 py-3 text-sm">
      <div className="flex items-baseline justify-between gap-4">
        <span className="font-medium text-text-primary">{workout.activity_label}</span>
        <span className="tabular-nums text-text-primary">{sleepDuration(workout.duration_min)}</span>
      </div>
      <p className="text-text-secondary">
        {nightLabel(workout.date)}, {wallClock(workout.start)}
        {details.length > 0 && ` · ${details.join(' · ')}`}
      </p>
    </li>
  );
}
