// [review:need-review] PHASE-01/42-mobile-categories-and-detail
// summary: shared UI constants used by both shells — touch target size, the editor field styling, the human labels of the category enums and the accessible names of the mobile editor sheets

import type {
  CategoryDisplayMode,
  CategoryStreakMode,
  FieldCreate,
} from '@/lib/api';

/** Apple HIG minimum touch target, in CSS px. */
export const TAP_TARGET_PX = 44;

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
