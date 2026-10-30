// [review:need-review] PHASE-03/238, PHASE-02/69
// summary: the sleep section both /health and /m/health render — the last night (asleep, bedtime and wake time on the phone's own clock, minutes per stage) and the week of nights by wake date; a link into the sleep detail screen when the caller names one, nothing before the answer, an honest line when no night arrived

import Link from 'next/link';
import type { HealthSleepNight } from '@/lib/api';
import { dayLabel } from '@/lib/health';

const MINUTES_PER_HOUR = 60;

type StageKey =
  | 'core_min'
  | 'deep_min'
  | 'rem_min'
  | 'unspecified_min'
  | 'awake_min'
  | 'in_bed_min';

/** Stages in the order the Health app lists them; zero rows are left out. */
const STAGES: ReadonlyArray<{ key: StageKey; label: string }> = [
  { key: 'core_min', label: 'Основной' },
  { key: 'deep_min', label: 'Глубокий' },
  { key: 'rem_min', label: 'REM' },
  { key: 'unspecified_min', label: 'Сон без фазы' },
  { key: 'awake_min', label: 'Бодрствование' },
  { key: 'in_bed_min', label: 'В кровати' },
];

export const SLEEP_EMPTY_TEXT =
  'Ночей за неделю нет: сон приходит с телефона вместе с остальными метриками.';

/** `430` → `7 ч 10 мин`; the same wording the week review uses. */
export function sleepDuration(minutes: number): string {
  const total = Math.round(minutes);
  const hours = Math.floor(total / MINUTES_PER_HOUR);
  const rest = total % MINUTES_PER_HOUR;
  if (hours === 0) return `${rest} мин`;
  return rest === 0 ? `${hours} ч` : `${hours} ч ${rest} мин`;
}

/**
 * `HH:MM` as the phone's clock showed it. The server sends the instant with the
 * offset the phone lived at, so the time is read from the string, not converted
 * into the reader's zone: a night in New York stays "23:40" when read in Berlin.
 */
export function wallClock(instant: string): string {
  return /T(\d{2}:\d{2})/.exec(instant)?.[1] ?? '';
}

/** Kept under its sleep name for the callers that already import it. */
export const nightLabel = dayLabel;

export interface SleepSectionProps {
  /** Oldest first; null while loading or after a failed read. */
  nights: HealthSleepNight[] | null;
  /** Where the sleep detail screen lives; sleep has no row in the catalog groups, so this is its way in. */
  detailHref?: string;
  /** Name of the nights list; the detail screen reads a period, not a week. */
  listLabel?: string;
}

export default function SleepSection({
  nights,
  detailHref,
  listLabel = 'Ночи недели',
}: SleepSectionProps) {
  if (nights === null) return null;

  const last = nights.at(-1);
  return (
    <section aria-labelledby="health-sleep" className="space-y-2">
      <h2 id="health-sleep" className="text-sm font-semibold text-text-secondary">
        Сон
      </h2>
      {detailHref !== undefined && (
        <Link
          href={detailHref}
          className="inline-flex min-h-11 items-center text-sm font-medium text-lime"
        >
          Все ночи
        </Link>
      )}
      <div className="overflow-hidden rounded-3xl border border-white/5 bg-card">
        {last === undefined ? (
          <p role="status" className="px-4 py-3 text-sm text-text-secondary">
            {SLEEP_EMPTY_TEXT}
          </p>
        ) : (
          <>
            <LastNight night={last} />
            <ol aria-label={listLabel} className="border-t border-white/5">
              {nights.map((night) => (
                <li
                  key={night.date}
                  className="flex min-h-11 items-center justify-between gap-4 px-4 py-2 text-sm"
                >
                  <span className="text-text-secondary">{nightLabel(night.date)}</span>
                  <span className="tabular-nums text-text-primary">
                    {sleepDuration(night.asleep_min)}
                  </span>
                </li>
              ))}
            </ol>
          </>
        )}
      </div>
    </section>
  );
}

function LastNight({ night }: { night: HealthSleepNight }) {
  const stages = STAGES.filter(({ key }) => night[key] > 0);
  return (
    <div className="space-y-3 px-4 py-4">
      <div>
        <p className="text-2xl font-semibold tabular-nums text-text-primary">
          {sleepDuration(night.asleep_min)}
        </p>
        <p className="text-sm text-text-secondary">
          Ночь на {nightLabel(night.date)}: отбой {wallClock(night.bedtime)}, подъём{' '}
          {wallClock(night.wake_time)}
        </p>
      </div>
      {stages.length > 0 && (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
          {stages.map(({ key, label }) => (
            <div key={key} className="flex justify-between gap-2">
              <dt className="text-text-secondary">{label}</dt>
              <dd className="tabular-nums text-text-primary">
                {sleepDuration(night[key])}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}
