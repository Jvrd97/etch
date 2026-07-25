// [review:need-review] PHASE-01/56-local-calendar-date-instead-of-utc
// summary: single source of truth for the `YYYY-MM-DD` date strings the API speaks — local calendar date

const ISO_DATE_PAD = 2;

/**
 * `d` rendered as the `YYYY-MM-DD` string the API expects — the calendar date
 * **in the user's local timezone**. The year/month/day are read off the local
 * calendar and zero-padded to two chars, so an instant is dated by the day the
 * user was living, not by its UTC projection.
 *
 * This matters east of Greenwich: at UTC+3, 2026-07-24T00:30 local is
 * 2026-07-23T21:30Z, yet it is still the 24th for the user, so it yields
 * `2026-07-24` — an entry logged just after midnight stays on the current day.
 */
export function toISODate(d: Date): string {
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(ISO_DATE_PAD, '0');
  const day = String(d.getDate()).padStart(ISO_DATE_PAD, '0');
  return `${year}-${month}-${day}`;
}

/**
 * Today as a `YYYY-MM-DD` string. `now` is injectable so callers (and tests)
 * can pin the moment instead of reading the wall clock.
 */
export function todayISO(now: Date = new Date()): string {
  return toISODate(now);
}
