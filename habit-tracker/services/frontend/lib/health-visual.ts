// [review:need-review] PHASE-03/303
// summary: the arithmetic behind the Health screen visuals — the word and tone of the day's index, the segments of its ring, the steps and energy tiles, the seven sleep bars (deep+REM against light, best night), the deviation bars around the personal norm and the 30-day workout totals; pure functions over the data the screens already read, no formula of its own for the index

import type { HealthMetric, HealthSleepNight, HealthWorkout } from '@/lib/api';
import { shiftDate, sparklinePoints } from '@/lib/health';
import type { TrendPoint } from '@/lib/trends';

/** Lime is the project token; sky and amber are the sleep and warning accents of the Health screen. */
export const HEALTH_COLORS = {
  lime: 'var(--lime)',
  sky: '#7fd6ff',
  amber: '#ffb454',
} as const;

export type HealthTone = 'good' | 'warn';

// ---------------------------------------------------------------- index of the day

const SCORE_WORDS: Readonly<Record<string, { word: string; tone: HealthTone }>> = {
  excellent: { word: 'Отличное', tone: 'good' },
  good: { word: 'Хорошее', tone: 'good' },
  fair: { word: 'Среднее', tone: 'warn' },
  moderate: { word: 'Среднее', tone: 'warn' },
  poor: { word: 'Сниженное', tone: 'warn' },
  low: { word: 'Сниженное', tone: 'warn' },
};

/** The word for the server's label; a label this screen has no word for prints no word, not a guess. */
export function scoreWord(label: string | null): { word: string; tone: HealthTone } | null {
  return label === null ? null : (SCORE_WORDS[label] ?? null);
}

export const RING_SEGMENTS = 24;
const MAX_SCORE = 100;

/** How many of the ring's segments the index lights; a nonzero index lights at least one. */
export function litSegments(value: number, segments: number = RING_SEGMENTS): number {
  const clamped = Math.min(Math.max(value, 0), MAX_SCORE);
  const lit = Math.round((clamped / MAX_SCORE) * segments);
  return clamped > 0 ? Math.max(lit, 1) : 0;
}

export interface RingTick {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

const RING_START_RAD = -Math.PI / 2;
const COORDINATE_DECIMALS = 2;

/** The ticks of a segmented ring, clockwise from twelve o'clock. */
export function ringTicks(
  segments: number,
  center: number,
  innerRadius: number,
  outerRadius: number
): RingTick[] {
  const round = (n: number) => Number(n.toFixed(COORDINATE_DECIMALS));
  return Array.from({ length: segments }, (_, index) => {
    const angle = RING_START_RAD + (index / segments) * 2 * Math.PI;
    return {
      x1: round(center + Math.cos(angle) * innerRadius),
      y1: round(center + Math.sin(angle) * innerRadius),
      x2: round(center + Math.cos(angle) * outerRadius),
      y2: round(center + Math.sin(angle) * outerRadius),
    };
  });
}

// ---------------------------------------------------------------- steps and energy tiles

export const STEPS_IDENTIFIER = 'HKQuantityTypeIdentifierStepCount';
export const ENERGY_IDENTIFIER = 'HKQuantityTypeIdentifierActiveEnergyBurned';

export function findMetric(
  metrics: readonly HealthMetric[],
  identifier: string
): HealthMetric | undefined {
  return metrics.find((metric) => metric.identifier === identifier);
}

export interface TileSeries {
  latest: { date: string; value: number } | null;
  /** Mean of the days that hold data; null when none does. */
  average: number | null;
  points: TrendPoint[];
}

export function tileSeries(metric: HealthMetric): TileSeries {
  const latest = metric.days.at(-1) ?? null;
  if (latest === null) return { latest: null, average: null, points: [] };
  const sum = metric.days.reduce((total, day) => total + day.value, 0);
  return {
    latest,
    average: sum / metric.days.length,
    points: sparklinePoints(metric.days, latest.date),
  };
}

// ---------------------------------------------------------------- deviation from the norm

/** The metrics whose deviation from the personal norm the screen draws; the colour never decides alone, the text says "вне обычного" too. */
export const DEVIATION_METRICS: ReadonlyArray<{ identifier: string; label: string }> = [
  { identifier: 'HKQuantityTypeIdentifierRestingHeartRate', label: 'Пульс покоя' },
  { identifier: 'HKQuantityTypeIdentifierHeartRateVariabilitySDNN', label: 'ВСР' },
  { identifier: 'HKQuantityTypeIdentifierRespiratoryRate', label: 'Дыхание' },
];

/** A bar reaches the edge of its track at this many usual spreads from the mean. */
export const FULL_SCALE_SPREADS = 2;

export interface DeviationRow {
  identifier: string;
  label: string;
  metric: HealthMetric;
  /** -1..1 around the zero line; null while the metric has too little history for a norm. */
  ratio: number | null;
  tone: HealthTone;
}

/** The position of a deviation on its track: against a constant history any step away fills the track. */
export function deviationRatio(deviation: number, stddev: number): number {
  if (deviation === 0) return 0;
  if (stddev <= 0) return Math.sign(deviation);
  return Math.max(-1, Math.min(1, deviation / (stddev * FULL_SCALE_SPREADS)));
}

export function deviationRows(metrics: readonly HealthMetric[]): DeviationRow[] {
  return DEVIATION_METRICS.flatMap(({ identifier, label }) => {
    const metric = findMetric(metrics, identifier);
    if (metric === undefined || metric.days.length === 0) return [];
    const { baseline } = metric;
    return [
      {
        identifier,
        label,
        metric,
        ratio: baseline === null ? null : deviationRatio(baseline.deviation, baseline.stddev),
        tone: baseline?.outside_typical ? 'warn' : 'good',
      },
    ];
  });
}

// ---------------------------------------------------------------- sleep bars

export const SLEEP_NIGHTS_SHOWN = 7;
const MINUTES_PER_HOUR = 60;
/** A short week must not look like a tall one: the track is at least this tall in minutes. */
const MIN_SLEEP_SCALE_MIN = 8 * MINUTES_PER_HOUR;

export interface SleepBar {
  date: string;
  night: HealthSleepNight | null;
  deepRemMin: number;
  lightMin: number;
  isBest: boolean;
}

export function sleepBars(
  nights: readonly HealthSleepNight[],
  endDate: string,
  count: number = SLEEP_NIGHTS_SHOWN
): { bars: SleepBar[]; scaleMin: number } {
  const byDate = new Map(nights.map((night) => [night.date, night]));
  const window = Array.from({ length: count }, (_, index) =>
    shiftDate(endDate, index - (count - 1))
  );
  const present = window.flatMap((date) => byDate.get(date) ?? []);
  const best = present.length < 2 ? null : present.reduce((a, b) => (b.asleep_min >= a.asleep_min ? b : a));
  const bars = window.map((date): SleepBar => {
    const night = byDate.get(date) ?? null;
    return {
      date,
      night,
      deepRemMin: night === null ? 0 : night.deep_min + night.rem_min,
      lightMin: night === null ? 0 : night.core_min + night.unspecified_min,
      isBest: night !== null && night === best,
    };
  });
  const longest = Math.max(0, ...present.map((night) => night.asleep_min));
  return { bars, scaleMin: Math.max(longest, MIN_SLEEP_SCALE_MIN) };
}

/** `Пн`, `Вт` … for a calendar date. */
export function weekdayLabel(isoDate: string): string {
  return new Intl.DateTimeFormat('ru-RU', { weekday: 'short', timeZone: 'UTC' }).format(
    new Date(`${isoDate}T00:00:00Z`)
  );
}

// ---------------------------------------------------------------- workouts

export interface WorkoutTotal {
  key: string;
  label: string;
  count: number;
  minutes: number;
  energyKcal: number | null;
  distanceM: number | null;
}

function addKnown(total: number | null, value: number | null): number | null {
  return value === null ? total : (total ?? 0) + value;
}

/** The workouts of the window summed per kind, the longest-trained kind first; a number HealthKit never held stays null. */
export function workoutTotals(workouts: readonly HealthWorkout[]): WorkoutTotal[] {
  const totals = new Map<string, WorkoutTotal>();
  for (const workout of workouts) {
    const current = totals.get(workout.activity_type) ?? {
      key: workout.activity_type,
      label: workout.activity_label,
      count: 0,
      minutes: 0,
      energyKcal: null,
      distanceM: null,
    };
    totals.set(workout.activity_type, {
      ...current,
      count: current.count + 1,
      minutes: current.minutes + workout.duration_min,
      energyKcal: addKnown(current.energyKcal, workout.energy_kcal),
      distanceM: addKnown(current.distanceM, workout.distance_m),
    });
  }
  return [...totals.values()].sort((a, b) => b.minutes - a.minutes);
}
