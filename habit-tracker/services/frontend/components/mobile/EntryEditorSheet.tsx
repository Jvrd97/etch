'use client';
// [review:need-review] PHASE-01/42-mobile-categories-and-detail, PHASE-01/73-category-field-reorder
// summary: the mobile shell's single entry editor — the full-screen sheet around useEntryDraft, shared by /m/entries (create and edit) and /m/categories/[id] (quick-add locked to one category)

import { FieldValueInput } from '@/components/FieldValueInput';
import FullScreenSheet from '@/components/mobile/FullScreenSheet';
import { useEntryDraft } from '@/hooks/useEntryDraft';
import type { Category, Entry } from '@/lib/api';
import { orderedFields } from '@/lib/today-categories';
import { NEW_ENTRY_SHEET_TITLE, TAP_TARGET_PX, entryInputClass } from '@/lib/ui-constants';

/** Shown as the sheet's title when the edited entry points at a category that is gone. */
export const UNKNOWN_CATEGORY_NAME = 'Unknown category';

export interface EntryEditorSheetProps {
  /** Categories the entry may be logged into; the first one is the default. */
  categories: Category[];
  /** Entry being edited. Absent means the sheet creates a new one. */
  entry?: Entry | null;
  /**
   * Category the entry is fixed to, when the screen already decided it —
   * `/m/categories/[id]` knows which category the user is looking at.
   */
  lockedCategory?: Category | null;
  onCancel: () => void;
  onSaved: () => void;
}

/**
 * The entry editor of the mobile shell: the sheet supplies the chrome,
 * `useEntryDraft` the state and the save.
 *
 * Its three uses — create, edit and quick-add — differ in exactly one thing,
 * whether the user still gets to choose a category. Editing keeps the entry in
 * the category it was logged into, and a locked category was already chosen by
 * the route, so in both cases the picker is dropped rather than offered as a
 * way to move the entry somewhere else by accident.
 */
export default function EntryEditorSheet({
  categories,
  entry = null,
  lockedCategory = null,
  onCancel,
  onSaved,
}: EntryEditorSheetProps) {
  // A locked category narrows the draft's world to itself: `useEntryDraft`
  // resolves the target by lookup, so handing it the full list plus a starting
  // id would leave a switch reachable that the screen means to forbid.
  const draftCategories = lockedCategory ? [lockedCategory] : categories;
  const draft = useEntryDraft({
    categories: draftCategories,
    entry,
    categoryId: lockedCategory?.id,
    onSaved,
  });
  const category = draft.category;
  const canPickCategory = !entry && !lockedCategory;

  return (
    <FullScreenSheet
      title={entry ? (category?.name ?? UNKNOWN_CATEGORY_NAME) : NEW_ENTRY_SHEET_TITLE}
      onCancel={onCancel}
      onDone={() => void draft.save()}
      busy={draft.saving}
      error={draft.error}
      onDismissError={draft.dismissError}
    >
      {canPickCategory && (
        <div>
          <label
            htmlFor="entry-category"
            className="block text-[13px] font-medium text-text-secondary mb-2"
          >
            Category
          </label>
          <select
            id="entry-category"
            value={draft.categoryId}
            onChange={(e) => draft.setCategoryId(Number(e.target.value))}
            style={{ minHeight: TAP_TARGET_PX }}
            className={entryInputClass}
          >
            {categories.map((option) => (
              <option key={option.id} value={option.id}>
                {option.name}
              </option>
            ))}
          </select>
        </div>
      )}

      <div>
        <label
          htmlFor="entry-date"
          className="block text-[13px] font-medium text-text-secondary mb-2"
        >
          Date
        </label>
        <input
          id="entry-date"
          type="date"
          value={draft.entryDate}
          onChange={(e) => draft.setEntryDate(e.target.value)}
          required
          style={{ minHeight: TAP_TARGET_PX }}
          className={entryInputClass}
        />
      </div>

      {category &&
        orderedFields(category).map((field) => (
          <div key={field.id}>
            <label
              htmlFor={`entry-field-${field.id}`}
              className="block text-[13px] font-medium text-text-secondary mb-2"
            >
              {field.name} {field.is_required && '*'}
            </label>
            <FieldValueInput
              id={`entry-field-${field.id}`}
              field={field}
              value={draft.values[field.id] || ''}
              onChange={(value) => draft.setValue(field.id, value)}
            />
          </div>
        ))}

      <div>
        <label
          htmlFor="entry-notes"
          className="block text-[13px] font-medium text-text-secondary mb-2"
        >
          Notes
        </label>
        <textarea
          id="entry-notes"
          value={draft.notes}
          onChange={(e) => draft.setNotes(e.target.value)}
          rows={3}
          className={entryInputClass}
        />
      </div>
    </FullScreenSheet>
  );
}
