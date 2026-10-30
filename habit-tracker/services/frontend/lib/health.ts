// [review:need-review] PHASE-02/68, PHASE-02/69
// summary: vocabulary of the metric detail screen — the periods of the daily series, the 24 hour slots (an hour without data is a null slot, never skipped), the link a catalog row points at, how a value, a deviation from the metric's own baseline and an hour range print, and the 30-day sparkline points with a gap kept as a gap

import type { HealthBaseline, HealthDayValue, HealthHourValue } from "@/lib/api";
import type { TrendPoint } from "@/lib/trends";

export const HOURS_PER_DAY = 24;

/** Sleep has no group row in the catalog list; its detail screen is opened by this identifier. */
export const SLEEP_IDENTIFIER = "HKCategoryTypeIdentifierSleepAnalysis";

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

/** Days the list sparkline covers, counting the last one. */
export const SPARKLINE_DAYS = 30;

/** `YYYY-MM-DD` shifted by whole days, on the calendar alone (no timezone arithmetic). */
export function shiftDate(isoDate: string, days: number): string {
  const moment = new Date(`${isoDate}T00:00:00Z`);
  moment.setUTCDate(moment.getUTCDate() + days);
  return moment.toISOString().slice(0, 10);
}

/**
 * The `count` calendar days ending at `endDate`, oldest first. A day the server
 * sent nothing for is a null point — a gap in the line, never a zero.
 */
export function sparklinePoints(
  days: readonly HealthDayValue[],
  endDate: string,
  count: number = SPARKLINE_DAYS,
): TrendPoint[] {
  if (days.length === 0) return [];
  const byDate = new Map(days.map((day) => [day.date, day.value]));
  return Array.from({ length: count }, (_, index) => {
    const date = shiftDate(endDate, index - (count - 1));
    return { date, value: byDate.get(date) ?? null };
  });
}

/** `+0.4 кг к обычному`, or `как обычно` when the day sits exactly on the mean. */
export function deviationText(baseline: HealthBaseline, unit: string): string {
  const rounded = Number(baseline.deviation.toFixed(ROUND_DIGITS));
  if (rounded === 0) return "как обычно";
  return `${rounded > 0 ? "+" : "−"}${formatValue(Math.abs(rounded))} ${unit} к обычному`;
}

/** The marker next to a deviation beyond the metric's usual spread; text, so colour is not the only signal. */
export const OUTSIDE_TYPICAL_TEXT = "вне обычного";

/** `2026-10-20` → `20 окт.`, on the calendar date alone. */
export function dayLabel(isoDate: string): string {
  return new Intl.DateTimeFormat("ru-RU", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  }).format(new Date(`${isoDate}T00:00:00Z`));
}
