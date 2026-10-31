// [review:need-review] PHASE-03/252, PHASE-03/264
// summary: calendar arithmetic on a `YYYY-MM-DD` string for the screens that learn the server's day from GET /day-mode — kept out of lib/date.ts, which suites replace wholesale with a one-function mock; #264 adds `localNoonOf`, the moment of a server day for date arithmetic

/** `YYYY-MM-DD` shifted by whole days, on the calendar and not on the clock. */
export function shiftDay(iso: string, days: number): string {
  const moment = new Date(`${iso}T00:00:00Z`);
  moment.setUTCDate(moment.getUTCDate() + days);
  return moment.toISOString().slice(0, 10);
}

const LOCAL_NOON_HOUR = 12;

/**
 * `YYYY-MM-DD` as local noon of that day: the moment for code that formats or steps
 * a `Date` by the local calendar (`todayISO(now)`, `setDate`), which no zone or
 * daylight switch moves to another date.
 */
export function localNoonOf(iso: string): Date {
  const [year, month, day] = iso.split('-').map(Number);
  return new Date(year, month - 1, day, LOCAL_NOON_HOUR);
}
