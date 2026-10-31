// [review:need-review] PHASE-03/303
// summary: «Сон по ночам» — seven columns by wake date, deep and REM against light sleep, the longest night in lime, a night that never arrived left as an empty slot; the last night's bedtime and wake time on the phone's own clock below; a link into the sleep detail screen; nothing before the answer, an honest line when no night arrived

import Link from 'next/link';
import type { HealthSleepNight } from '@/lib/api';
import { localDate } from '@/lib/health-metrics';
import { HEALTH_COLORS, sleepBars, weekdayLabel } from '@/lib/health-visual';
import { SLEEP_EMPTY_TEXT, nightLabel, sleepDuration, wallClock } from './SleepSection';

const TRACK_HEIGHT_PX = 144;
const PERCENT = 100;
const LIGHT_OPACITY = 0.35;

export interface SleepNightsChartProps {
  /** Oldest first; null while loading or after a failed read. */
  nights: HealthSleepNight[] | null;
  /** Where the sleep detail screen lives. */
  detailHref?: string;
}

export default function SleepNightsChart({ nights, detailHref }: SleepNightsChartProps) {
  if (nights === null) return null;

  const last = nights.at(-1);
  const { bars, scaleMin } = sleepBars(nights, localDate());
  const percent = (minutes: number) => `${(minutes / scaleMin) * PERCENT}%`;

  return (
    <section
      aria-labelledby="health-sleep"
      className="rounded-3xl border border-white/5 bg-card p-5"
    >
      <div className="flex items-center justify-between gap-3">
        <h2 id="health-sleep" className="text-sm font-semibold text-text-secondary">
          Сон по ночам
        </h2>
        {detailHref !== undefined && (
          <Link
            href={detailHref}
            className="inline-flex min-h-11 items-center text-sm font-medium text-lime"
          >
            Все ночи
          </Link>
        )}
      </div>

      {last === undefined ? (
        <p role="status" className="mt-2 text-sm text-text-secondary">
          {SLEEP_EMPTY_TEXT}
        </p>
      ) : (
        <>
          <p className="text-2xl font-semibold tabular-nums text-text-primary">
            {sleepDuration(last.asleep_min)}
          </p>
          <p className="text-sm text-text-secondary">
            Ночь на {nightLabel(last.date)}: отбой {wallClock(last.bedtime)}, подъём{' '}
            {wallClock(last.wake_time)}
          </p>

          <ol aria-label="Ночи недели" className="mt-4 grid grid-cols-7 gap-2">
            {bars.map((bar) => (
              <li key={bar.date} className="flex min-w-0 flex-col items-center gap-1">
                <div
                  className="flex w-full max-w-9 flex-col justify-end"
                  style={{ height: TRACK_HEIGHT_PX }}
                  aria-hidden="true"
                >
                  {bar.night !== null && (
                    <>
                      <div
                        className="rounded-t-md"
                        style={{
                          height: percent(bar.lightMin),
                          backgroundColor: bar.isBest ? HEALTH_COLORS.lime : HEALTH_COLORS.sky,
                          opacity: LIGHT_OPACITY,
                        }}
                      />
                      <div
                        className="rounded-b-md"
                        style={{
                          height: percent(bar.deepRemMin),
                          backgroundColor: bar.isBest ? HEALTH_COLORS.lime : HEALTH_COLORS.sky,
                        }}
                      />
                    </>
                  )}
                </div>
                <span className="text-xs text-text-secondary" aria-hidden="true">
                  {weekdayLabel(bar.date)}
                </span>
                <span className="sr-only">
                  {nightLabel(bar.date)}:{' '}
                  {bar.night === null
                    ? 'ночи нет'
                    : `${sleepDuration(bar.night.asleep_min)}, глубокий и REM ${sleepDuration(bar.deepRemMin)}${bar.isBest ? ', лучшая ночь' : ''}`}
                </span>
              </li>
            ))}
          </ol>

          <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-secondary">
            <LegendItem color={HEALTH_COLORS.sky} label="Глубокий и REM" />
            <LegendItem color={HEALTH_COLORS.sky} label="Лёгкий" opacity={LIGHT_OPACITY} />
            <LegendItem color={HEALTH_COLORS.lime} label="Самая долгая ночь" />
          </ul>
        </>
      )}
    </section>
  );
}

function LegendItem({ color, label, opacity = 1 }: { color: string; label: string; opacity?: number }) {
  return (
    <li className="flex items-center gap-1.5">
      <span
        aria-hidden="true"
        className="size-2.5 rounded-sm"
        style={{ backgroundColor: color, opacity }}
      />
      {label}
    </li>
  );
}
