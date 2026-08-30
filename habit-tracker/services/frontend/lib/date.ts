// [review:need-review] PHASE-01/59-previousday-mixed-utc-local, PHASE-03/94
// summary: single source of truth for the `YYYY-MM-DD` date strings the API speaks — local calendar date, and since #94 the inverse the timeline needs to step through weeks and months

/** Width of the zero-padded month/day fields in a `YYYY-MM-DD` string. */
export const ISO_DATE_PAD = 2;

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

/**
 * A `YYYY-MM-DD` string as a Date at **local** midnight.
 *
 * Parsed field by field rather than through `new Date(string)`, which the
 * specification reads as UTC: east of Greenwich that lands the previous evening,
 * and a square of the timeline would then sit in the wrong week. The inverse of
 * `toISODate`, and here for the same reason it is — so there is one answer.
 */
export function fromISODate(value: string): Date {
  const [year, month, day] = value.split('-').map(Number);
  return new Date(year, month - 1, day);
}
