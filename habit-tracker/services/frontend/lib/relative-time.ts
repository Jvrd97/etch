// [review:need-review] PHASE-01/73-dashboard-hero-today-ring
// summary: pure formatting of an API timestamp into "14 minutes ago" / "on 5 Mar 2026", plus the hero's "Logged …" wording

const MS_PER_SECOND = 1000;
const SECONDS_PER_MINUTE = 60;
const MINUTES_PER_HOUR = 60;
const HOURS_PER_DAY = 24;

const MS_PER_MINUTE = MS_PER_SECOND * SECONDS_PER_MINUTE;
const MS_PER_HOUR = MS_PER_MINUTE * MINUTES_PER_HOUR;
const MS_PER_DAY = MS_PER_HOUR * HOURS_PER_DAY;

/**
 * Past this age a day count stops being something a person can picture
 * ("83 days ago"), so the absolute day is shown instead.
 */
const ABSOLUTE_AFTER_DAYS = 7;

/** Shown when the timestamp cannot be parsed — vague, but never wrong. */
const UNKNOWN_AGE = 'recently';

const ABSOLUTE_DAY_FORMAT: Intl.DateTimeFormatOptions = {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
};

/** A timestamp already carrying `Z` or a `±hh:mm` / `±hhmm` offset. */
const HAS_TIMEZONE = /(?:Z|[+-]\d{2}:?\d{2})$/;

/**
 * The instant `iso` denotes, or `null` if it denotes none.
 *
 * A timestamp without a timezone designator is read as UTC, not as local time.
 * The API stores instants in UTC; letting the browser assume local time would
 * shift such a value by the user's offset and turn a record saved a minute ago
 * into one saved three hours ago (or, east of Greenwich, into the future).
 */
function parseInstant(iso: string): Date | null {
  const normalized = HAS_TIMEZONE.test(iso) ? iso : `${iso}Z`;
  const parsed = new Date(normalized);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function pluralize(count: number, unit: string): string {
  return `${count} ${unit}${count === 1 ? '' : 's'}`;
}

/**
 * How long ago `iso` happened, phrased for a person: `just now`,
 * `14 minutes ago`, `4 hours ago`, `6 days ago`, then `on 5 Mar 2026`.
 *
 * `now` is injectable so callers (and tests) can pin the moment instead of
 * reading the wall clock. A timestamp in the future — the client clock running
 * behind the server's — is reported as `just now` rather than as a negative
 * age: a record cannot have been saved later than it was read.
 */
export function formatRelativeTime(iso: string, now: Date = new Date()): string {
  const instant = parseInstant(iso);
  if (instant === null) return UNKNOWN_AGE;

  const elapsedMs = now.getTime() - instant.getTime();
  if (elapsedMs < MS_PER_MINUTE) return 'just now';
  if (elapsedMs < MS_PER_HOUR) {
    return `${pluralize(Math.floor(elapsedMs / MS_PER_MINUTE), 'minute')} ago`;
  }
  if (elapsedMs < MS_PER_DAY) {
    return `${pluralize(Math.floor(elapsedMs / MS_PER_HOUR), 'hour')} ago`;
  }

  const days = Math.floor(elapsedMs / MS_PER_DAY);
  if (days < ABSOLUTE_AFTER_DAYS) return `${pluralize(days, 'day')} ago`;

  return `on ${new Intl.DateTimeFormat('en-GB', ABSOLUTE_DAY_FORMAT).format(instant)}`;
}

/**
 * The hero's timing line for an entry.
 *
 * The verb is deliberate: `created_at` is the moment the record was saved, not
 * the moment the thing happened. A day entered in the evening would otherwise
 * claim the workout took place at 21:40.
 */
export function formatLoggedAgo(iso: string, now: Date = new Date()): string {
  return `Logged ${formatRelativeTime(iso, now)}`;
}
