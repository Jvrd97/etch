// [review:need-review] PHASE-01/73-dashboard-hero-today-ring
// summary: shared UI constants used by both shells — touch target, editor field styling, category enum labels, mobile sheet names, and the dashboard hero's wording (ring caption, empty day, last-entry headline)

import type {
  CategoryDisplayMode,
  CategoryStreakMode,
  FieldCreate,
} from '@/lib/api';
import type { HeroLastEntry } from '@/lib/dashboard-stats';

/** Apple HIG minimum touch target, in CSS px. */
export const TAP_TARGET_PX = 44;

/**
 * Caption under the hero ring. It names the day on purpose: the number inside
 * the ring counts today, and a bare "entries" is how the old ring came to read
 * as a lifetime total.
 */
export const ENTRIES_TODAY_LABEL = 'entries today';

/** Hero headline on a day nothing has been written yet. */
export const NO_ENTRIES_YET = 'Nothing logged today yet';

/**
 * The hero's headline for the last thing written: `Last entry: Pushups 30`.
 *
 * The value is appended bare, and is allowed to be absent. Units arrive with
 * #75 and are not part of the entry yet, so the line has to read correctly with
 * a naked number now and keep reading correctly once a unit joins it.
 */
export function heroLastEntryLine(lastEntry: HeroLastEntry | null): string {
  if (lastEntry === null) return NO_ENTRIES_YET;
  const value = lastEntry.value === null ? '' : ` ${lastEntry.value}`;
  return `Last entry: ${lastEntry.categoryName}${value}`;
}

/**
 * Colour a category starts on, and the swatch drawn for one that carries none.
 *
 * Shared rather than per-component: the editor picks it as the initial value
 * while three separate screens fall back to it when `category.color` is empty,
 * and a private copy in any of them is an entry card that stops matching the
 * category it belongs to the first time the brand colour changes.
 */
export const DEFAULT_CATEGORY_COLOR = '#B8FF36';

/**
 * Styling of a single entry-editor control (input, select, textarea).
 *
 * Lives here rather than next to one of the editors: all three of them — the
 * desktop modal, the inline card editor and the mobile sheet — style their
 * fields identically, and importing it from a component made that component a
 * de-facto style module for the others.
 */
export const entryInputClass =
  'w-full px-4 py-3 bg-surface border border-white/10 rounded-2xl text-text-primary placeholder:text-text-disabled outline-none transition-all duration-200 focus:border-lime focus:ring-2 focus:ring-lime/25';

/**
 * Denser sibling of `entryInputClass` for the controls nested inside a field
 * row of the desktop category modal.
 *
 * A row is already a card inside the form, so its controls step down a level:
 * `bg-card` on the surface the row sits on, smaller text and tighter padding.
 * Named rather than inlined because the row spells it three times — name, type
 * and options — and three copies drift apart on the first restyle.
 */
export const compactInputClass =
  'w-full px-3 py-2.5 bg-card border border-white/10 rounded-2xl text-sm text-text-primary placeholder:text-text-disabled outline-none transition-all duration-200 focus:border-lime focus:ring-2 focus:ring-lime/25';

/**
 * The up/down button that moves a field row within the category editor.
 *
 * Quiet by design: reordering is a rearrangement, not a destructive action, so
 * the arrows read as secondary next to Remove. The disabled state has to look
 * inert rather than merely dim — at the ends of the list it is the only signal
 * that the press did nothing.
 */
export const reorderButtonClass =
  'inline-flex items-center justify-center rounded-xl text-text-secondary transition-colors duration-200 hover:text-text-primary disabled:text-text-disabled disabled:cursor-not-allowed disabled:hover:text-text-disabled';

/**
 * Human labels of the category enums and of the field types.
 *
 * Both shells render the same three pickers and the same summary lines, so the
 * wording lives once here: a label changed on one screen only is a category
 * that reads as two different things depending on which shell you opened it in.
 * `Record` over the union rather than a loose map, so adding a variant to the
 * API type fails the build here instead of rendering an empty option.
 */
export const DISPLAY_MODE_LABELS: Record<CategoryDisplayMode, string> = {
  form: 'Form',
  checklist: 'Checklist',
};

export const STREAK_MODE_LABELS: Record<CategoryStreakMode, string> = {
  build: 'Build habit',
  avoid: 'Avoid',
};

/**
 * The `show_in_today` tri-state as a `<select>` speaks it.
 *
 * A select rather than a checkbox because the field has three states, and the
 * third one — "let the app decide" — is the default a checkbox has nowhere to
 * put. Encoded as strings so the option values survive the DOM round-trip that
 * would turn `null` into the string "null" anyway.
 */
export type ShowInTodayChoice = 'auto' | 'always' | 'never';

export const SHOW_IN_TODAY_LABELS: Record<ShowInTodayChoice, string> = {
  auto: 'Automatic',
  always: 'Always show',
  never: 'Never show',
};

/** Label of the visibility control, spelled once so both shells agree. */
export const SHOW_IN_TODAY_LABEL = 'Show on Today';

/** The stored tri-state as the select's current choice. */
export function showInTodayChoice(value: boolean | null | undefined): ShowInTodayChoice {
  if (value === true) return 'always';
  if (value === false) return 'never';
  return 'auto';
}

/** The select's choice as the stored tri-state. */
export function showInTodayValue(choice: ShowInTodayChoice): boolean | null {
  if (choice === 'always') return true;
  if (choice === 'never') return false;
  return null;
}

export const FIELD_TYPE_LABELS: Record<FieldCreate['field_type'], string> = {
  text: 'Text',
  number: 'Number',
  boolean: 'Boolean',
  duration: 'Duration (time spent)',
  date: 'Date',
  datetime: 'DateTime',
  time: 'Time',
  select: 'Select',
};

/**
 * Accessible name of the mobile sheet that creates an entry.
 *
 * Deliberately different from the "New entry" button that opens it: a button
 * and a dialog sharing a name are two indistinguishable nodes in the
 * accessibility tree. It lives here rather than in `app/m/entries/page.tsx`
 * because the test asserts on it, and arbitrary named exports out of an App
 * Router `page.tsx` are a contract Next does not promise to keep.
 */
export const NEW_ENTRY_SHEET_TITLE = 'Log an entry';

/**
 * Accessible name of the mobile sheet that creates a category — the same
 * button-versus-dialog distinction as `NEW_ENTRY_SHEET_TITLE`, and here too the
 * test needs a name it can import from somewhere other than a `page.tsx`.
 */
export const NEW_CATEGORY_SHEET_TITLE = 'Set up a category';
