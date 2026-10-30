// [review:need-review] PHASE-03/209, PHASE-03/272
// summary: shared Health screen vocabulary — the groups the whole Apple Health catalog (all but cycle tracking) is drawn under, today in the reader's own timezone, the "catalog has nothing yet" test, and the Apple access link both shells point at

import type { HealthMetric, HealthMetricGroup } from '@/lib/api';

/**
 * Groups the server's metric catalog is filed under, in display order.
 *
 * Named here rather than inline in each page: `/health` and `/m/health` read
 * the same catalog and have to agree on which heading a metric prints under,
 * and a second copy of this list is the classic way the two shells drift.
 */
export const HEALTH_GROUPS: ReadonlyArray<{ id: HealthMetricGroup; title: string }> = [
  { id: 'movement', title: 'Движение и энергия' },
  { id: 'heart', title: 'Сердце и дыхание' },
  { id: 'body', title: 'Тело' },
  { id: 'nutrition', title: 'Питание' },
  { id: 'mobility', title: 'Подвижность' },
  { id: 'hearing', title: 'Слух' },
  { id: 'mind', title: 'Осознанность' },
  { id: 'symptoms', title: 'Симптомы' },
  { id: 'other', title: 'Другое' },
];

/** Today in the reader's own timezone, as the backend's `date_from`/`date_to` want it. */
export function localDate(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

/**
 * Whether the catalog has not a single day of data anywhere in it.
 *
 * A metric with an empty `days` array is an ordinary, per-row "Нет данных" —
 * the phone simply never measured that one thing. Every metric empty at once is
 * a different fact: nothing has ever synced, and a wall of identical empty rows
 * would say that quietly instead of telling the reader what to do about it.
 */
export function isCatalogEmpty(metrics: readonly HealthMetric[]): boolean {
  return metrics.every((metric) => metric.days.length === 0);
}

/** Shown instead of the catalog when nothing has ever synced. */
export const HEALTH_SYNC_HINT =
  'Данных ещё нет — откройте приложение на телефоне и нажмите синк.';

export const HEALTH_ACCESS_LABEL = 'Настройки доступа';

export const HEALTH_ACCESS_URL =
  'https://support.apple.com/guide/iphone/share-health-and-fitness-data-iph5ede58c3d/ios';
