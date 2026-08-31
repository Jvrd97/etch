// [review:need-review] PHASE-03/priemka-5.7
// summary: the one reading of a stored moment as wall clock — `clock()` for a single end, `clockRange()` for a window; five copies of this arithmetic lived in lib/ and components/ until the acceptance of the phase found three different answers to one unreadable moment

/**
 * The wall clock a moment shows, in the reader's own zone.
 *
 * The browser's zone is right here and wrong nowhere else in this system: the
 * server decided which *day* the moment belongs to, and this only decides what
 * the clock on the wall in front of the reader says.
 *
 * An unreadable moment answers with an empty string rather than with the raw
 * string or with `NaN:NaN`. Both of those put a non-clock into a slot the
 * screen reads as a clock — and one of the slots is an editable field, where
 * `NaN:NaN` is a value a person would then be asked to correct by hand.
 */
export function clock(moment: string): string {
  const at = new Date(moment);
  if (Number.isNaN(at.getTime())) return '';
  const hours = String(at.getHours()).padStart(2, '0');
  const minutes = String(at.getMinutes()).padStart(2, '0');
  return `${hours}:${minutes}`;
}

/** `09:30-11:00` — the shape a window had when plans were files. */
export function clockRange(startsAt: string, endsAt: string): string {
  return `${clock(startsAt)}-${clock(endsAt)}`;
}
