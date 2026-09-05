// [review:need-review] PHASE-01/41-mobile-entries-fullscreen-sheet, PHASE-01/73-category-field-reorder, #176
// summary: pure conversions between an entry's stored values and what the UI needs — the field-id-keyed draft the editors hold and the field-named list the cards render; shared by useEntryDraft, EntryCard and the mobile list

import type { Category, Entry, EntryValueCreate } from './api';
import { orderedFields } from './today-categories';
import { formatValue } from './format-value';

/** What an entry editor holds while the user types: field id -> raw string value. */
export type EntryDraftValues = Record<number, string>;

/** Seed an edit draft from the values already stored on `entry`. */
export function draftValuesFromEntry(entry: Entry): EntryDraftValues {
  const draft: EntryDraftValues = {};
  for (const value of entry.values) {
    draft[value.field_id] = value.value;
  }
  return draft;
}

/**
 * Payload for create/update: one value per field of `category`, in field order.
 *
 * The category's fields — not the draft's keys — decide what is sent, so a
 * field the user left untouched still round-trips as an empty value, and a
 * stale draft key left over from another category is dropped instead of being
 * posted against a field that category does not own.
 */
export function toEntryValues(
  category: Category,
  values: EntryDraftValues
): EntryValueCreate[] {
  return orderedFields(category).map((field) => ({
    field_id: field.id,
    value: values[field.id] || '',
  }));
}

/** Label used when the field behind a stored value cannot be resolved. */
export const UNNAMED_FIELD_LABEL = 'Unknown field';

/** One stored value, ready to render: its field's name and the value itself. */
export interface LabelledValue {
  /** EntryValue id — stable list key. */
  id: number;
  label: string;
  value: string;
}

/**
 * Name each stored value after the field it belongs to, in stored order.
 *
 * Values outlive schema edits: a field dropped from the category (or the whole
 * category deleted) leaves values whose `field_id` resolves to nothing, and the
 * cards used to render a nameless box for them. The placeholder label keeps the
 * value readable instead.
 */
export function labelledValues(category: Category | undefined, entry: Entry): LabelledValue[] {
  return entry.values.map((value) => {
    const field = category?.fields.find((candidate) => candidate.id === value.field_id);
    return {
      id: value.id,
      label: field?.name ?? UNNAMED_FIELD_LABEL,
      value: formatValue(value.value, field?.unit),
    };
  });
}
