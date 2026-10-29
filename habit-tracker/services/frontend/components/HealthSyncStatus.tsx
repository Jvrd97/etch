// [review:need-review] PHASE-03/132
// summary: the "last sync / lag N h" block of /health and /m/health — a still person with a live pump reads "меньше часа", a phone dark for a day reads "отставание 24 ч", an abandoned run is named as abandoned; first on the screen so a day-old lag is visible without scrolling
import type { HealthSyncFailureKind, HealthSyncStatus } from '@/lib/api';

/** From this lag the block turns into a warning. */
export const HEALTH_LAG_WARNING_HOURS = 24;

const FAILURE_LABELS: Record<HealthSyncFailureKind, string> = {
  network: 'нет связи с сервером',
  unit: 'неверная единица измерения',
  unknown_metric: 'неизвестная метрика',
  auth: 'не прошла авторизация',
  unknown: 'причина неизвестна',
};

/** "меньше часа" under one hour, otherwise whole hours: "отставание 24 ч". */
export function lagLabel(lagHours: number): string {
  if (lagHours < 1) return 'меньше часа назад';
  return `отставание ${Math.floor(lagHours)} ч`;
}

interface Verdict {
  text: string;
  detail: string | null;
  warn: boolean;
}

function verdict(status: HealthSyncStatus): Verdict {
  const lastRun = status.last_runs[0];
  const failed = lastRun?.status === 'failed' ? lastRun : null;
  const failureDetail = failed
    ? `Последний прогон не удался: ${FAILURE_LABELS[failed.failure_kind ?? 'unknown']}`
    : null;

  if (status.lag_hours === null) {
    return {
      text: 'Синк ещё не проходил',
      detail: failureDetail,
      warn: true,
    };
  }
  const lag = lagLabel(status.lag_hours);
  const stale = status.lag_hours >= HEALTH_LAG_WARNING_HOURS;
  if (status.interrupted) {
    return {
      text: `Последний синк оборван — ${lag}`,
      detail: 'Телефон ушёл из сети посреди прогона; данные догрузятся при следующем синке.',
      warn: true,
    };
  }
  return { text: `Последний синк: ${lag}`, detail: failureDetail, warn: stale || failed !== null };
}

/** The block itself; renders nothing until the status has arrived. */
export default function HealthSyncStatus({ status }: { status: HealthSyncStatus | null }) {
  if (status === null) return null;
  const { text, detail, warn } = verdict(status);
  const tone = warn ? 'bg-warning/10 text-warning' : 'bg-card text-text-secondary';

  return (
    <div role="status" className={`rounded-3xl border border-white/5 px-4 py-3 ${tone}`}>
      <p className="text-sm font-medium">{text}</p>
      {detail && <p className="mt-1 text-xs">{detail}</p>}
    </div>
  );
}
