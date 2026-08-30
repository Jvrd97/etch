// [review:need-review] PHASE-03/122
// summary: which key belongs to which quick mark and what one keystroke means — the single assignment table the keydown handler, the caption on the button and the legend all read, plus the guards that keep a keystroke aimed at a text field out of the day's numbers

import type { QuickMark } from '@/lib/api';

/**
 * The digits handed out by position: the first nine buttons of the directory,
 * one row of keys, no modifier. A tenth button gets a digit only by being
 * given one in `hotkey`.
 */
const POSITIONAL_KEYS = '123456789';

/** The key that shows the legend. Shift is part of typing it on most layouts. */
const LEGEND_KEY = '?';

/** Elements that swallow a keystroke because the user is writing into them. */
const TYPING_TAGS = new Set(['input', 'textarea', 'select']);

/** What one keystroke means on Today. */
export type HotkeyAction =
  | { kind: 'mark'; quickMarkId: number }
  | { kind: 'legend' }
  | { kind: 'none' };

const NO_ACTION: HotkeyAction = { kind: 'none' };

/**
 * The part of a keyboard event this module reads.
 *
 * A DOM `KeyboardEvent` satisfies it as it is; tests build the shape by hand,
 * which is what keeps the decision testable without a browser. `target` stays
 * `unknown` because the answer is "is the user typing into it", not "is it an
 * `HTMLElement`" — a plain object standing in for a field must answer too.
 */
export interface HotkeyEvent {
  key: string;
  /**
   * The physical key, independent of the layout in force. It is what makes a
   * letter hotkey survive a switch to Cyrillic, where the `p` key types `з`.
   */
  code: string;
  ctrlKey: boolean;
  metaKey: boolean;
  altKey: boolean;
  shiftKey: boolean;
  repeat: boolean;
  target: unknown;
}

/** Everything outside the event that changes what a keystroke means. */
export interface HotkeyScope {
  /** The directory as the server ordered it — position is what hands out digits. */
  marks: QuickMark[];
  /**
   * True while a modal is on screen (the legend itself, the full entry editor).
   * A dialog owns the keyboard for as long as it is up.
   */
  dialogOpen: boolean;
}

/** One line of the legend: the key, and what pressing it does. */
export interface HotkeyLegendRow {
  quickMarkId: number;
  label: string;
  /** null for a button that has no key — it is reachable by mouse only. */
  key: string | null;
}

/**
 * A one-character key in the single case comparisons are done in.
 *
 * Anything longer is a named key (`Enter`, `ArrowDown`) and belongs to nobody.
 * Lowercasing is what makes a `hotkey` of `W` answer to the `w` the user can
 * actually press without Shift.
 */
function normalizeKey(key: string | null): string | null {
  if (key === null || key.length !== 1) return null;
  return key.toLowerCase();
}

/**
 * The character engraved on the physical key, or null for anything else.
 *
 * `KeyP` is `KeyP` in every layout; `event.key` at the same moment is `p` on a
 * Latin layout and `з` on a Cyrillic one. Without this, a letter hotkey would
 * work only while the user happened to be typing in English — and this user
 * switches layouts all day.
 */
function physicalKey(code: string): string | null {
  if (/^Key[A-Z]$/.test(code)) return code.slice(3).toLowerCase();
  if (/^Digit[0-9]$/.test(code)) return code.slice(5);
  return null;
}

/**
 * The keys one keystroke could mean, most literal first.
 *
 * The character actually typed is tried before the engraving: a `hotkey` the
 * user set to a character they can see themselves typing must win over the
 * Latin letter sharing that key's plastic.
 */
function pressedKeys(event: HotkeyEvent): string[] {
  const typed = normalizeKey(event.key);
  const physical = physicalKey(event.code);
  const keys: string[] = [];
  if (typed !== null) keys.push(typed);
  if (physical !== null && physical !== typed) keys.push(physical);
  return keys;
}

/**
 * True when the keystroke is landing in something the user is writing into.
 *
 * This is the rule that keeps "250" typed into a number field from reading as
 * "press buttons 2, 5 and 0". `contenteditable` counts: the journal composer
 * is not an `<input>` but takes text all the same.
 */
function isTypingTarget(target: unknown): boolean {
  if (typeof target !== 'object' || target === null) return false;
  const element = target as { tagName?: unknown; isContentEditable?: unknown };
  if (element.isContentEditable === true) return true;
  const tag = typeof element.tagName === 'string' ? element.tagName.toLowerCase() : '';
  return TYPING_TAGS.has(tag);
}

/**
 * The key each button answers to, in the directory's own order.
 *
 * One table, three readers: the keydown handler resolves through it, the button
 * prints its own entry, and the legend lists all of them. That is what keeps
 * the key printed on a button and the key that actually fires it from drifting
 * apart.
 *
 * A `hotkey` given by hand is claimed first and beats the position it would
 * otherwise have taken; the button that loses its digit to it shows no key
 * rather than a digit that fires somewhere else. Sorting out such a collision
 * at the point where the button is created is #125 — here the display only
 * refuses to lie about it.
 */
export function hotkeyAssignment(marks: QuickMark[]): (string | null)[] {
  const taken = new Set<string>();

  const explicit = marks.map((mark) => {
    const key = normalizeKey(mark.hotkey);
    if (key === null || taken.has(key)) return null;
    taken.add(key);
    return key;
  });

  return explicit.map((key, index) => {
    if (key !== null) return key;
    const digit = index < POSITIONAL_KEYS.length ? POSITIONAL_KEYS[index] : null;
    if (digit === null || taken.has(digit)) return null;
    taken.add(digit);
    return digit;
  });
}

/** The legend, in the order the buttons are drawn in. */
export function hotkeyLegendRows(marks: QuickMark[]): HotkeyLegendRow[] {
  const keys = hotkeyAssignment(marks);
  return marks.map((mark, index) => ({
    quickMarkId: mark.id,
    label: mark.label,
    key: keys[index] ?? null,
  }));
}

/**
 * What one keystroke on Today means: a mark, the legend, or nothing.
 *
 * Nothing is the answer by default, and five separate conditions produce it.
 * A dialog is up, so it owns the keyboard. The keystroke is being typed into a
 * field. It is a key held down — repeat is deliberately silent, since a held
 * key adding a litre of water a second is not a feature (#122 Out of Scope).
 * It carries Cmd, Ctrl or Alt, which the browser has first claim on — `Cmd+1`
 * switches tabs and must keep doing exactly that. Or no button answers to it.
 *
 * `?` is checked before the Shift guard because Shift is how it is typed; every
 * other key with Shift held is a different keystroke and marks nothing.
 */
export function resolveHotkey(event: HotkeyEvent, scope: HotkeyScope): HotkeyAction {
  if (scope.dialogOpen) return NO_ACTION;
  if (isTypingTarget(event.target)) return NO_ACTION;
  if (event.repeat) return NO_ACTION;
  if (event.ctrlKey || event.metaKey || event.altKey) return NO_ACTION;

  // An empty directory has nothing to mark and nothing to explain.
  if (scope.marks.length === 0) return NO_ACTION;
  if (event.key === LEGEND_KEY) return { kind: 'legend' };
  if (event.shiftKey) return NO_ACTION;

  const assignment = hotkeyAssignment(scope.marks);
  for (const key of pressedKeys(event)) {
    const index = assignment.indexOf(key);
    if (index !== -1) return { kind: 'mark', quickMarkId: scope.marks[index].id };
  }
  return NO_ACTION;
}
