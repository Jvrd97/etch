// [review:need-review] PHASE-03/303
// summary: the «Состояние сегодня» card — the server's index of the day as a word, a number out of 100 and a segmented ring, captioned as the mean of the last 7 days (and by how many days of data when fewer); two honest lines for a missing number (under three days of data, or three and more with no personal norm yet); a label this screen has no word for; nothing at all while the index is missing

import type { HealthScore } from '@/lib/api';
import {
  HEALTH_COLORS,
  RING_SEGMENTS,
  litSegments,
  ringTicks,
  scoreWord,
} from '@/lib/health-visual';

const RING_SIZE = 120;
const RING_CENTER = RING_SIZE / 2;
const RING_INNER_RADIUS = 44;
const RING_OUTER_RADIUS = 56;
const TICK_WIDTH = 5;

/** The server needs three days of data for an index. */
const MIN_BASIS_DAYS = 3;
/** The index is the mean over this window, not the value of today. */
const WINDOW_DAYS = 7;

export const SCORE_FEW_DAYS_TEXT = 'Данных пока мало: синхронизируйте телефон';
export const SCORE_NO_NORM_TEXT = 'Личная норма ещё не набралась: нужно больше дней данных';

export interface HealthStateCardProps {
  /** Null while the answer is missing, or the endpoint is not there yet. */
  score: HealthScore | null;
}

function daysText(days: number): string {
  const lastTwo = days % 100;
  const last = days % 10;
  if (last === 1 && lastTwo !== 11) return `${days} дню`;
  return `${days} дням`;
}

export default function HealthStateCard({ score }: HealthStateCardProps) {
  if (score === null) return null;

  const { value } = score;
  const word = scoreWord(score.label);
  const tone = word?.tone ?? 'good';
  const color = tone === 'good' ? HEALTH_COLORS.lime : HEALTH_COLORS.amber;
  const lit = value === null ? 0 : litSegments(value);

  return (
    <section
      aria-labelledby="health-state"
      className="rounded-3xl border border-white/5 bg-card p-5"
    >
      <h2 id="health-state" className="text-sm font-semibold text-text-secondary">
        Состояние сегодня
      </h2>
      <div className="mt-3 flex items-center gap-5">
        <div className="relative shrink-0" style={{ width: RING_SIZE, height: RING_SIZE }}>
          <svg
            aria-hidden="true"
            focusable="false"
            viewBox={`0 0 ${RING_SIZE} ${RING_SIZE}`}
            width={RING_SIZE}
            height={RING_SIZE}
          >
            {ringTicks(RING_SEGMENTS, RING_CENTER, RING_INNER_RADIUS, RING_OUTER_RADIUS).map(
              (tick, index) => (
                <line
                  key={index}
                  x1={tick.x1}
                  y1={tick.y1}
                  x2={tick.x2}
                  y2={tick.y2}
                  stroke={index < lit ? color : 'rgba(255,255,255,0.1)'}
                  strokeWidth={TICK_WIDTH}
                  strokeLinecap="round"
                />
              )
            )}
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className="text-3xl font-bold tabular-nums text-text-primary">
              {value === null ? '—' : value}
            </span>
            {value !== null && <span className="text-xs text-text-secondary">из 100</span>}
          </div>
        </div>
        <div className="min-w-0 space-y-1">
          {value === null ? (
            <p role="status" className="text-sm text-text-secondary">
              {score.basis_days < MIN_BASIS_DAYS ? SCORE_FEW_DAYS_TEXT : SCORE_NO_NORM_TEXT}
            </p>
          ) : (
            <>
              {word !== null && (
                <p
                  className="text-2xl font-semibold"
                  style={{ color }}
                >
                  {word.word}
                </p>
              )}
              <p className="text-sm text-text-secondary">
                {score.basis_days < WINDOW_DAYS
                  ? `За ${WINDOW_DAYS} дней, по ${daysText(score.basis_days)} данных`
                  : `За ${WINDOW_DAYS} дней`}
              </p>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
