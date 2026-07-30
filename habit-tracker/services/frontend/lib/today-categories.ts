// [review:need-review] PHASE-01/28-today-avoid-card
// summary: pure Today-page category partitioning (avoid streak / checklist / quick-form) + field helpers

import type { Category, Field } from './api';

/** First number field of a category, ordered, or undefined if none. */
export function firstNumberField(category: Category): Field | undefined {
  return [...category.fields]
    .sort((a, b) => a.order - b.order)
    .find((f) => f.field_type === 'number');
}

/** Boolean fields of a category, ordered. */
export function booleanFields(category: Category): Field[] {
  return [...category.fields]
    .filter((f) => f.field_type === 'boolean')
    .sort((a, b) => a.order - b.order);
}

/** An avoid category plus its optional "how much" number field. */
export interface AvoidItem {
  category: Category;
  numberField: Field | undefined;
}

/**
 * A card on the Today screen, with the number field its quick input increments.
 *
 * `numberField` is undefined only for a category the user pinned by hand that
 * has nothing to increment: it still gets a card, because the card is also the
 * way into the full entry editor.
 */
export interface QuickFormItem {
  category: Category;
  numberField: Field | undefined;
}

/** Today-page categories split by how they should be rendered. */
export interface TodayGroups {
  avoid: AvoidItem[];
  checklist: Category[];
  quickForm: QuickFormItem[];
}

/**
 * Route each category to its Today-screen renderer.
 *
 * `show_in_today` decides *whether* the category is on the screen; the rules
 * below decide *how* it is drawn, and the user does not get to override that.
 * Pinning an avoid category still yields a streak card, and pinning a checklist
 * still yields its boolean row — asking to see something is not asking to see
 * it as a different kind of thing.
 *
 * `false` removes the category from every group without touching `is_active`:
 * off the screen, still tracked everywhere else.
 *
 * Absent or `null` falls through to the heuristic this screen has always used:
 * avoid-streak categories first (a streak card, never a quick input), then
 * checklist categories with boolean fields, then categories with a number field
 * as quick inputs. A checklist saved before boolean fields were required falls
 * through to quick-form, matching the legacy fallback the page relied on.
 */
export function partitionTodayCategories(categories: Category[]): TodayGroups {
  const avoid: AvoidItem[] = [];
  const checklist: Category[] = [];
  const quickForm: QuickFormItem[] = [];

  for (const category of categories) {
    if (category.show_in_today === false) continue;
    const pinned = category.show_in_today === true;

    if (category.streak_mode === 'avoid') {
      avoid.push({ category, numberField: firstNumberField(category) });
      continue;
    }

    if (category.display_mode === 'checklist' && booleanFields(category).length > 0) {
      checklist.push(category);
      continue;
    }

    const numberField = firstNumberField(category);
    const byHeuristic =
      numberField !== undefined &&
      (category.display_mode === 'form' || booleanFields(category).length === 0);
    // A pinned category earns a card even with nothing to increment: the card
    // opens the full editor, which is the whole point of pinning one.
    if (pinned || byHeuristic) {
      quickForm.push({ category, numberField });
    }
  }

  return { avoid, checklist, quickForm };
}
