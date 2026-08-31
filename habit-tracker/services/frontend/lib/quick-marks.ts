// [review:need-review] PHASE-03/121, PHASE-03/124, PHASE-03/130
// summary: pure reading of the quick-mark directory — the caption a button shows, the state the tap's own answer folds back into the list without a refetch, the categories the directory has taken over from the legacy quick-input card, the same fold for an undo, the caption the undo affordance carries, the key that makes a retried tap the same tap, and the word a planned button says out loud to a reader who cannot see that it is first

import type { QuickMark, QuickMarkEvent, QuickMarkUndo } from '@/lib/api';

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
  const planned = mark.planned ? `${mark.label} — в плане на сегодня` : mark.label;
  return mark.done ? `${planned} — отмечено` : planned;
}

/**
 * The directory with one button's state replaced by what its undo answered.
 *
 * The same fold as `applyQuickMarkEvent`, and deliberately a second function
 * rather than a shared one over a union: the two answers happen to carry the
 * same two fields today, and collapsing them would tie the undo response to the
 * tap response for no reason beyond that coincidence.
 */
export function applyQuickMarkUndo(
  marks: QuickMark[],
  undone: QuickMarkUndo
): QuickMark[] {
  return marks.map((mark) =>
    mark.id === undone.quick_mark_id
      ? { ...mark, today_total: undone.today_total, done: undone.done }
      : mark
  );
}

/**
 * What the undo affordance says, or null when there is nothing to take back.
 *
 * Names the button the tap belongs to, because the affordance sits under a row
 * of them and «Отменить» alone would not say which. An event whose button has
 * since left the directory answers null: an undo nobody can attribute is worse
 * than no undo at all.
 */
export function undoCaption(
  marks: QuickMark[],
  event: QuickMarkEvent | null
): string | null {
  if (event === null) return null;
  const mark = marks.find((candidate) => candidate.id === event.quick_mark_id);
  return mark ? `Отменить «${mark.label}»` : null;
}

/**
 * A key that makes a retried tap the same tap.
 *
 * The whole point of the retry: a connection that drops mid-send leaves the
 * client unable to tell a lost request from a lost answer, and sending the
 * second attempt under the key of the first is what keeps the day's sum from
 * doubling. `crypto.randomUUID` is absent on http:// origins in some browsers,
 * so the fallback is a value only this tab produces — uniqueness across tabs is
 * enough, because the key only has to distinguish this tap from the next one.
 */
export function newTapKey(): string {
  const uuid = globalThis.crypto?.randomUUID?.();
  if (uuid) return `tap-${uuid}`;
  return `tap-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** The badge a planned button carries, so "first" is not the only signal. */
export const PLANNED_BADGE = 'в плане';

/**
 * The state a tap leaves the button's plan line in, folded back into the list.
 *
 * The server closes the line as part of the tap; the screen only has to stop
 * promising that it is still open. Nothing here re-derives which line that was
 * — `plan_item_id` came with the button, and recomputing it in the browser
 * would be a second answer to a question the server already answered.
 */
export function plannedItemIds(marks: QuickMark[]): Set<string> {
  const ids = new Set<string>();
  for (const mark of marks) {
    if (mark.plan_item_id !== null) ids.add(mark.plan_item_id);
  }
  return ids;
}
