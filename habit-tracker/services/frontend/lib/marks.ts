// [review:need-review] PHASE-03/88
// summary: pure reading of marks — the ring a click walks (пусто → done → failed → пусто), the marks of a day by item id, and the labels a tick and the four kinds of empty are said in

import type { Mark, MarkState, TaskCounts } from '@/lib/api';

/**
 * The ring a click walks, `null` being "no mark".
 *
 * Mirrors `app/day/marks.py` on the server, deliberately as data rather than as
 * an if-chain so the two can be compared by eye. `skipped` is not on it: "стало
 * неактуально" is a judgement about the plan rather than about the work, and a
 * person clicking a line four times must not land on it by accident.
 */
export const MARK_CYCLE: (MarkState | null)[] = [null, 'done', 'failed'];

/** The glyph a state is drawn as. `null` is an empty box, not a third glyph. */
export const MARK_GLYPH: Record<MarkState, string> = {
  done: '✓',
  failed: '✕',
  skipped: '–',
};

/** What the button says it will do, for a reader who is not looking at glyphs. */
export const MARK_LABEL: Record<MarkState, string> = {
  done: 'сделано',
  failed: 'не сделал',
  skipped: 'стало неактуально',
};

/** Said of a line nobody marked. */
export const MARK_PENDING_LABEL = 'не отмечено';

/** Shown where the day was never opened at all — the emptiest of the four empties. */
export const DAY_NEVER_OPENED = 'День не открывали ни разу';

/**
 * The state one click away from `current`.
 *
 * A state outside the ring — `skipped` — returns to пусто: clicking a line that
 * was set aside has to do something, and the only harmless something is to hand
 * it back to the ring.
 */
export function nextMarkState(current: MarkState | null): MarkState | null {
  const position = MARK_CYCLE.indexOf(current ?? null);
  if (position === -1) return null;
  return MARK_CYCLE[(position + 1) % MARK_CYCLE.length];
}

/** The marks of a day keyed by the item they belong to. */
export function marksByItem(marks: Mark[]): Map<string, Mark> {
  return new Map(marks.map((mark) => [mark.item_id, mark]));
}

/** The state of one item, `null` when it has no mark. */
export function stateOf(
  marks: Map<string, Mark>,
  itemId: string
): MarkState | null {
  return marks.get(itemId)?.state ?? null;
}

/** The note of one item, empty when it has none. */
export function noteOf(marks: Map<string, Mark>, itemId: string): string {
  return marks.get(itemId)?.note ?? '';
}

/** The plain name of a state, for a reader who is not looking at glyphs. */
export function markStateLabel(state: MarkState | null): string {
  return state === null ? MARK_PENDING_LABEL : MARK_LABEL[state];
}

/**
 * The line in the header: what happened to the day's tasks.
 *
 * `skipped` is named separately from both `done` and `failed`, and never folded
 * into either: a task that stopped being relevant was neither closed nor
 * missed, and counting it as one of the two makes the header lie in exactly the
 * direction the reader is trying to check.
 */
export function taskCountsLine(counts: TaskCounts): string {
  const parts = [`закрыто ${counts.done} из ${counts.planned}`];
  if (counts.failed > 0) parts.push(`не сделано ${counts.failed}`);
  if (counts.skipped > 0) parts.push(`снято ${counts.skipped}`);
  return parts.join(' · ');
}
