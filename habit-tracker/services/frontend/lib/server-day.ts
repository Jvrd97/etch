// [review:need-review] PHASE-03/252
// summary: calendar arithmetic on a `YYYY-MM-DD` string for the screens that learn the server's day from GET /day-mode — kept out of lib/date.ts, which suites replace wholesale with a one-function mock

/** `YYYY-MM-DD` shifted by whole days, on the calendar and not on the clock. */
export function shiftDay(iso: string, days: number): string {
  const moment = new Date(`${iso}T00:00:00Z`);
  moment.setUTCDate(moment.getUTCDate() + days);
  return moment.toISOString().slice(0, 10);
}
