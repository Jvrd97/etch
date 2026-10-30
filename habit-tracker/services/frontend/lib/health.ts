// [review:need-review] PHASE-02/68
// summary: vocabulary of the metric detail screen — the periods of the daily series, the 24 hour slots (an hour without data is a null slot, never skipped), the link a catalog row points at, and how a value and an hour range print

import type { HealthHourValue } from "@/lib/api";

export const HOURS_PER_DAY = 24;

/** Periods the daily series can be read over, in days counting today. */
export const HEALTH_PERIODS: ReadonlyArray<{ days: number; label: string }> = [
  { days: 7, label: "7 дней" },
  { days: 30, label: "30 дней" },
  { days: 90, label: "90 дней" },
];

export const DEFAULT_PERIOD_DAYS = 30;

/**
 * The 24 hours of a day, index = local hour.
 *
 * The server sends only the hours that hold data; a grid built from that list
 * alone would put 08:00 next to 18:00 and lie about the time of day. A null slot
 * is "no data", which is not a zero.
 */
export function hourSlots(
  hours: readonly HealthHourValue[],
): Array<HealthHourValue | null> {
  const slots: Array<HealthHourValue | null> = Array.from(
    { length: HOURS_PER_DAY },
    () => null,
  );
  for (const hour of hours) {
    if (hour.hour >= 0 && hour.hour < HOURS_PER_DAY) slots[hour.hour] = hour;
  }
  return slots;
}

export function hourLabel(hour: number): string {
  return `${String(hour).padStart(2, "0")}:00`;
}

/** Where a catalog row leads: `/health/<id>` on the desktop, `/m/health/<id>` on the phone. */
export function metricHref(basePath: string, identifier: string): string {
  return `${basePath}/${encodeURIComponent(identifier)}`;
}

const ROUND_DIGITS = 1;

/** Numbers print as the catalog list prints them: no trailing noise, one decimal at most. */
export function formatValue(value: number): string {
  return String(Number(value.toFixed(ROUND_DIGITS)));
}

/** `54–58` for an hour of a discrete metric whose readings differ; null when there is no range to show. */
export function hourRange(hour: HealthHourValue): string | null {
  if (hour.min === hour.max) return null;
  return `${formatValue(hour.min)}–${formatValue(hour.max)}`;
}
