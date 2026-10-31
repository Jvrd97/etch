// [review:need-review] #302
// summary: the three score rings - Здоровье (0..100, empty under three days of data), Привычки (share of marks done) and Челленджи (done of total); a ring without data shows a dash and says why instead of a zero

import type { DashboardScores } from '@/lib/api';
import { HEALTH_SCORE_MIN_DAYS, healthLabelText } from '@/lib/dashboard-summary';
import { countable } from '@/lib/plural';
import { DashboardCard } from './DashboardCard';

const RING_STROKE = 9;
const RING_SIZE_DESKTOP = 120;
const RING_SIZE_MOBILE = 92;
const TRACK_COLOR = 'rgba(255,255,255,0.08)';
/** `--color-lime`, `--color-green-secondary` and `--color-info` of `app/globals.css`; an SVG stroke cannot read a Tailwind token. */
const HEALTH_RING_COLOR = '#b8ff36';
const HABITS_RING_COLOR = '#69e76a';
const CHALLENGES_RING_COLOR = '#60a5fa';
/** Gap and dash of the empty track, in SVG units. */
const EMPTY_TRACK_DASH = '3 6';
const PERCENT = 100;

interface RingView {
  key: string;
  title: string;
  /** Fraction filled, 0..1; null draws an empty dashed track. */
  fraction: number | null;
  /** What sits in the middle of the ring. */
  centre: string;
  /** What is written under the title. */
  caption: string;
  color: string;
}

function clamp01(value: number): number {
  return Math.min(Math.max(value, 0), 1);
}

export function ringViews(scores: DashboardScores): RingView[] {
  const { health, habits, challenges } = scores;

  const healthView: RingView = (() => {
    const base = { key: 'health', title: 'Здоровье', color: HEALTH_RING_COLOR };
    if (health.value === null) {
      // Three days are there but the server still gave no score: the personal norm has not formed.
      const enoughDays = health.basis_days >= HEALTH_SCORE_MIN_DAYS;
      return {
        ...base,
        fraction: null,
        centre: '—',
        caption: enoughDays
          ? 'Нормы пока нет'
          : `Мало данных: ${health.basis_days} из ${HEALTH_SCORE_MIN_DAYS} дн.`,
      };
    }
    const label = healthLabelText(health.label);
    const days = countable(health.basis_days, 'день', 'дня', 'дней');
    return {
      ...base,
      fraction: clamp01(health.value / PERCENT),
      centre: String(Math.round(health.value)),
      caption: label === null ? `за ${days}` : `${label} · за ${days}`,
    };
  })();

  const habitsView: RingView = (() => {
    const base = { key: 'habits', title: 'Привычки', color: HABITS_RING_COLOR };
    if (habits.total === null || habits.total === 0) {
      return { ...base, fraction: null, centre: '—', caption: 'План не задан' };
    }
    if (habits.value === null || habits.done === null) {
      return { ...base, fraction: null, centre: '—', caption: 'Нет данных' };
    }
    return {
      ...base,
      fraction: clamp01(habits.value / PERCENT),
      centre: `${Math.round(habits.value)}%`,
      caption: `${habits.done} из ${habits.total} отметок`,
    };
  })();

  const challengesView: RingView = (() => {
    const base = { key: 'challenges', title: 'Челленджи', color: CHALLENGES_RING_COLOR };
    if (challenges.total === null || challenges.done === null || challenges.total === 0) {
      return { ...base, fraction: null, centre: '—', caption: 'Челленджей нет' };
    }
    return {
      ...base,
      fraction: clamp01(challenges.done / challenges.total),
      centre: `${challenges.done}/${challenges.total}`,
      caption: 'выполнено',
    };
  })();

  return [healthView, habitsView, challengesView];
}

function Ring({ view, size, mobile }: { view: RingView; size: number; mobile: boolean }) {
  const radius = (size - RING_STROKE) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - (view.fraction ?? 0));
  return (
    <li className="flex min-w-0 flex-col items-center text-center">
      <div className="relative" style={{ width: size, height: size }}>
        <svg
          width={size}
          height={size}
          viewBox={`0 0 ${size} ${size}`}
          className="-rotate-90"
          aria-hidden="true"
        >
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={TRACK_COLOR}
            strokeWidth={RING_STROKE}
            strokeDasharray={view.fraction === null ? EMPTY_TRACK_DASH : undefined}
          />
          {view.fraction !== null && view.fraction > 0 && (
            <circle
              cx={size / 2}
              cy={size / 2}
              r={radius}
              fill="none"
              stroke={view.color}
              strokeWidth={RING_STROKE}
              strokeLinecap="round"
              strokeDasharray={circumference}
              strokeDashoffset={offset}
            />
          )}
        </svg>
        <span
          className={`absolute inset-0 flex items-center justify-center font-bold text-text-primary ${
            mobile ? 'text-xl' : 'text-3xl'
          }`}
        >
          {view.centre}
        </span>
      </div>
      <p className={`mt-3 font-medium text-text-primary ${mobile ? 'text-sm' : 'text-base'}`}>
        {view.title}
      </p>
      <p className="mt-0.5 text-[12px] leading-snug text-text-secondary">{view.caption}</p>
    </li>
  );
}

interface ScoreRingsProps {
  scores: DashboardScores;
  mobile?: boolean;
}

export function ScoreRings({ scores, mobile = false }: ScoreRingsProps) {
  const size = mobile ? RING_SIZE_MOBILE : RING_SIZE_DESKTOP;
  return (
    <DashboardCard title="Общий показатель" mobile={mobile}>
      <ul className="grid grid-cols-3 gap-2 sm:gap-4">
        {ringViews(scores).map((view) => (
          <Ring key={view.key} view={view} size={size} mobile={mobile} />
        ))}
      </ul>
    </DashboardCard>
  );
}
