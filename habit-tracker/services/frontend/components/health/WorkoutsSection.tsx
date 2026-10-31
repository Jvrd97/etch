// [review:need-review] PHASE-02/70, PHASE-03/303
// summary: the workouts section both /health and /m/health render — the last 30 days summed per kind (count, active time, energy and distance only where HealthKit held them, a bar of time against the busiest kind), then the five newest workouts as events (type, day and start time on the phone's own clock, active time, then the numbers HealthKit held); nothing before the answer, an honest line when none arrived

import type { HealthWorkout } from '@/lib/api';
import { HEALTH_COLORS, workoutTotals, type WorkoutTotal } from '@/lib/health-visual';
import { nightLabel, sleepDuration, wallClock } from './SleepSection';

const METERS_PER_KILOMETER = 1000;
const FRACTION_DIGITS = 1;
const PERCENT = 100;
/** Below this many minutes the total reads as «62 мин», above it as hours. */
const MINUTES_AS_HOURS_FROM = 120;
const NEWEST_SHOWN = 5;

export const WORKOUTS_EMPTY_TEXT =
  'Тренировок за 30 дней нет: они приходят с телефона вместе с остальными метриками.';

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

/** `62 мин`, but `3 ч 20 мин` once the minutes pass two hours. */
export function activeTime(minutes: number): string {
  return minutes < MINUTES_AS_HOURS_FROM ? `${Math.round(minutes)} мин` : sleepDuration(minutes);
}

/** `1 тренировка`, `3 тренировки`, `5 тренировок`. */
export function workoutsCount(count: number): string {
  const lastTwo = count % 100;
  const last = count % 10;
  if (last === 1 && lastTwo !== 11) return `${count} тренировка`;
  if (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14)) return `${count} тренировки`;
  return `${count} тренировок`;
}

/** `62 мин · 480 ккал · 5,2 км`: time always, energy and distance only where HealthKit held them. */
export function totalDetails(total: WorkoutTotal): string[] {
  const details = [activeTime(total.minutes)];
  if (total.energyKcal !== null) details.push(`${Math.round(total.energyKcal)} ккал`);
  if (total.distanceM !== null) details.push(workoutDistance(total.distanceM));
  return details;
}

export interface WorkoutsSectionProps {
  /** Oldest first; null while loading or after a failed read. */
  workouts: HealthWorkout[] | null;
}

export default function WorkoutsSection({ workouts }: WorkoutsSectionProps) {
  if (workouts === null) return null;

  const newestFirst = [...workouts].reverse();
  const totals = workoutTotals(workouts);
  const busiest = totals[0]?.minutes ?? 0;
  const allMinutes = totals.reduce((sum, total) => sum + total.minutes, 0);
  return (
    <section
      aria-labelledby="health-workouts"
      className="rounded-3xl border border-white/5 bg-card p-5"
    >
      <h2 id="health-workouts" className="text-sm font-semibold text-text-secondary">
        Тренировки
      </h2>
      {newestFirst.length === 0 ? (
        <p role="status" className="mt-2 text-sm text-text-secondary">
          {WORKOUTS_EMPTY_TEXT}
        </p>
      ) : (
        <>
          <p className="text-sm text-text-secondary">
            За 30 дней: {workoutsCount(workouts.length)} · {activeTime(allMinutes)}
          </p>
          <ul aria-label="Тренировки по видам" className="mt-4 space-y-4">
            {totals.map((total) => (
              <li key={total.key}>
                <div className="flex items-baseline justify-between gap-4 text-sm">
                  <span className="font-medium text-text-primary">
                    {total.label}
                    <span className="ml-2 font-normal text-text-secondary">× {total.count}</span>
                  </span>
                  <span className="text-right tabular-nums text-text-secondary">
                    {totalDetails(total).join(' · ')}
                  </span>
                </div>
                <div aria-hidden="true" className="mt-1.5 h-2 rounded-full bg-white/10">
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${(total.minutes / busiest) * PERCENT}%`,
                      backgroundColor: HEALTH_COLORS.lime,
                    }}
                  />
                </div>
              </li>
            ))}
          </ul>
          <h3 className="mt-5 text-xs font-semibold text-text-secondary">Последние</h3>
          <ol aria-label="Последние тренировки" className="divide-y divide-white/5">
            {newestFirst.slice(0, NEWEST_SHOWN).map((workout) => (
              <WorkoutRow key={workout.id} workout={workout} />
            ))}
          </ol>
        </>
      )}
    </section>
  );
}

function WorkoutRow({ workout }: { workout: HealthWorkout }) {
  const details = workoutDetails(workout);
  return (
    <li className="space-y-0.5 py-3 text-sm">
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
