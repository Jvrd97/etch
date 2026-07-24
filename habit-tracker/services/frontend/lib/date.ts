// [review:need-review] PHASE-01/40-mobile-shell-toggle-manifest-today
// summary: single source of truth for the `YYYY-MM-DD` date strings the API speaks

/**
 * `d` rendered as the `YYYY-MM-DD` string the API expects — the calendar date
 * **in UTC**, not in the user's timezone: the instant is converted to UTC first
 * and only then truncated. Zero-padding comes from the ISO representation
 * itself, so single-digit months and days stay two chars.
 *
 * Consequence, deliberately kept for now: east of Greenwich the early hours of
 * the day still map to yesterday. At UTC+3, 2026-07-24T01:30 local is
 * 2026-07-23T22:30Z and yields `2026-07-23`, so an entry logged after midnight
 * lands on the previous day. Switching to the local calendar date is tracked in
 * PHASE-01/56 — it changes what every screen writes, so it is its own slice.
 */
export function toISODate(d: Date): string {
  return d.toISOString().split('T')[0];
}

/**
 * Today as a `YYYY-MM-DD` string. `now` is injectable so callers (and tests)
 * can pin the moment instead of reading the wall clock.
 */
export function todayISO(now: Date = new Date()): string {
  return toISODate(now);
}
