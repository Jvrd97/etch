// [review:need-review] PHASE-01/27-streak-mode-endpoint, PHASE-01/28-today-avoid-card, PHASE-03/90
// summary: pure label helpers for the avoid-streak block (day count, clean badge, last relapse date); #90 examined the date renderer and left it as it is — it holds no day boundary to move

const RELAPSE_DATE_FORMAT: Intl.DateTimeFormatOptions = {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
};

/** Streak length with the correct English day form, e.g. "1 day" / "42 days". */
export function formatDays(days: number): string {
  return `${days} ${days === 1 ? 'day' : 'days'}`;
}

/** Avoid-streak badge text, e.g. "1 day clean" / "42 days clean". */
export function formatCleanDays(days: number): string {
  return `${formatDays(days)} clean`;
}

/**
 * Readable last-relapse day; "never" when the streak was never broken.
 * The ISO date is parsed as UTC so the rendered day never shifts by timezone.
 *
 * This is a renderer of a date-only string, not a day boundary, which is why
 * `#90` moved the server onto `local_date()` and left this alone: `parsed` has
 * no time in it, and reading it in the viewer's zone would print the previous
 * day everywhere west of Greenwich — the very shift the ticket exists to remove.
 */
export function formatLastRelapse(isoDate: string | null): string {
  if (!isoDate) return 'never';
  const parsed = new Date(`${isoDate}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return isoDate;
  return new Intl.DateTimeFormat('en-GB', {
    ...RELAPSE_DATE_FORMAT,
    timeZone: 'UTC',
  }).format(parsed);
}
