// [review:need-review] PHASE-03/121
// summary: pure reading of the quick-mark directory — the caption a button shows, the state the tap's own answer folds back into the list without a refetch, and the categories the directory has taken over from the legacy quick-input card

import type { QuickMark, QuickMarkEvent } from '@/lib/api';

/**
 * The number under a button's label, or '' when it has none.
 *
 * A tick answers with `today_total: null` — a box is not a quantity — and an
 * untouched number button answers null too, because the day holds no value for
 * it yet. Both render as nothing rather than as a zero: a zero is a fact about
 * the day ("я выпил ноль"), and a button nobody pressed has not stated it.
 */
export function formatMarkTotal(total: number | null): string {
  if (total === null) return '';
  return Number.isInteger(total) ? String(total) : String(Number(total.toFixed(3)));
}

/** The caption a button shows: its total and the unit it is counted in. */
export function markCaption(mark: QuickMark): string {
  const total = formatMarkTotal(mark.today_total);
  if (total === '') return '';
  return mark.unit_label ? `${total} ${mark.unit_label}` : total;
}

/**
 * The directory with one button's state replaced by what its tap answered.
 *
 * This is why a tap costs one network call: `POST .../events` returns
 * `today_total` and `done` for the button that was pressed, so the screen
 * repaints from the response instead of asking the directory again. An event
 * for a button that is no longer in the list leaves the list alone rather than
 * appending a half-built row.
 */
export function applyQuickMarkEvent(
  marks: QuickMark[],
  event: QuickMarkEvent
): QuickMark[] {
  return marks.map((mark) =>
    mark.id === event.quick_mark_id
      ? { ...mark, today_total: event.today_total, done: event.done }
      : mark
  );
}

/**
 * The categories the directory already answers for.
 *
 * Today drops its legacy quick-input card for exactly these: once a category
 * has a button, two ways to add to it on one screen is one too many. A category
 * with no button keeps its card, which is what makes an empty directory a
 * no-op rather than a screen with nothing on it.
 */
export function categoriesWithQuickMark(marks: QuickMark[]): Set<number> {
  return new Set(marks.map((mark) => mark.category_id));
}

/**
 * What the button says it will do, for a reader who is not looking at glyphs.
 *
 * Built from the label the user typed and the step the button carries, so a
 * button reads the same to a screen reader as it does on screen.
 */
export function markActionLabel(mark: QuickMark): string {
  return mark.done ? `${mark.label} — отмечено` : mark.label;
}
