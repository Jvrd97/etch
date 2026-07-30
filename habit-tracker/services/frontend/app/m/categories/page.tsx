'use client';
// [review:need-review] PHASE-01/62-mobile-onboarding-twin, PHASE-01/63-today-card-tap-and-visibility
// summary: mobile Categories screen — same data as the desktop page via useCategories, editing done in the full-screen sheet with every form control on its own row, each field card stacked instead of the desktop's two-up grid, and the Today-visibility choice

import { useState } from 'react';
import Link from 'next/link';
import { ChevronRight, FolderKanban, Pencil, Plus, Trash2, Wand2 } from 'lucide-react';
import ErrorAlert from '@/components/ErrorAlert';
import LoadingSpinner from '@/components/LoadingSpinner';
import FullScreenSheet from '@/components/mobile/FullScreenSheet';
import MobileHeaderAction from '@/components/mobile/HeaderAction';
import {
  DEFAULT_CATEGORY_COLOR,
  useCategories,
  useCategoryDraft,
} from '@/hooks/useCategories';
import type { Category, CategoryDisplayMode, CategoryStreakMode, FieldCreate } from '@/lib/api';
import { MOBILE_PATH_PREFIX } from '@/lib/routes';
import {
  DISPLAY_MODE_LABELS,
  FIELD_TYPE_LABELS,
  NEW_CATEGORY_SHEET_TITLE,
  SHOW_IN_TODAY_LABEL,
  SHOW_IN_TODAY_LABELS,
  STREAK_MODE_LABELS,
  TAP_TARGET_PX,
  entryInputClass,
  showInTodayChoice,
  showInTodayValue,
  type ShowInTodayChoice,
} from '@/lib/ui-constants';

/** What the editor sheet is currently doing; closed when null. */
type SheetState = { kind: 'create' } | { kind: 'edit'; category: Category };

/**
 * Accessible name of the button that opens the editor.
 *
 * Deliberately different from the sheet's own title: a button and a dialog
 * carrying the same name are two indistinguishable nodes in the accessibility
 * tree.
 */
const NEW_CATEGORY_BUTTON_LABEL = 'New category';

/** The mobile voice-category-builder, offered from the empty state. */
const ONBOARDING_PATH = `${MOBILE_PATH_PREFIX}/onboarding`;

export default function MobileCategoriesPage() {
  const { categories, loading, error, setError, reload, remove } = useCategories();
  const [sheet, setSheet] = useState<SheetState | null>(null);

  const handleDelete = async (category: Category) => {
    if (!confirm(`Delete ${category.name}? This will delete all related entries!`)) return;
    await remove(category.id);
  };

  if (loading) return <LoadingSpinner size="lg" />;

  // The page-level banner reports what happened to the list itself — a failed
  // load or delete. A failed save belongs inside the sheet, where the user is.
  const listError = error && <ErrorAlert message={error} onDismiss={() => setError(null)} />;

  const editor = sheet && (
    <CategoryEditorSheet
      // Remounting per target keeps the draft trivially correct: a freshly
      // opened sheet never inherits the previous category's values.
      key={sheet.kind === 'edit' ? sheet.category.id : 'new'}
      state={sheet}
      onCancel={() => setSheet(null)}
      onSaved={async () => {
        setSheet(null);
        await reload();
      }}
    />
  );

  if (categories.length === 0) {
    return (
      <div className="space-y-5 animate-fade-rise">
        {listError}
        <div className="text-center py-12 bg-card border border-white/5 rounded-3xl">
          <div className="inline-flex p-4 rounded-3xl bg-surface mb-4">
            <FolderKanban className="w-7 h-7 text-text-disabled" strokeWidth={2} />
          </div>
          <h2 className="text-base font-medium text-text-primary mb-1">Nothing here yet</h2>
          <p className="text-sm text-text-secondary px-6 mb-5">
            A category is what entries are logged into — start with one.
          </p>
          <button
            onClick={() => setSheet({ kind: 'create' })}
            style={{ minHeight: TAP_TARGET_PX }}
            className="inline-flex items-center justify-center px-6 py-3 bg-lime text-background rounded-3xl font-medium transition-transform duration-200 active:scale-95"
          >
            Create category
          </button>
          {/* Beside the form, not instead of it: the form builds one field at a
              time, which is the slow way in from nothing. Describing the setup
              in words is worth the most exactly here. */}
          <Link
            href={ONBOARDING_PATH}
            style={{ minHeight: TAP_TARGET_PX }}
            className="mt-3 inline-flex items-center justify-center gap-2 px-6 py-3 text-sm font-medium text-lime transition-transform duration-200 active:scale-95"
          >
            <Wand2 className="w-4 h-4" strokeWidth={2} />
            Describe them instead
          </Link>
        </div>
        {editor}
      </div>
    );
  }

  return (
    <div className="space-y-3 animate-fade-rise">
      {listError}

      {categories.map((category) => (
        <CategoryRow
          key={category.id}
          category={category}
          onEdit={() => setSheet({ kind: 'edit', category })}
          onDelete={() => void handleDelete(category)}
        />
      ))}

      <MobileHeaderAction
        label={NEW_CATEGORY_BUTTON_LABEL}
        onClick={() => setSheet({ kind: 'create' })}
      />

      {editor}
    </div>
  );
}

interface CategoryRowProps {
  category: Category;
  onEdit: () => void;
  onDelete: () => void;
}

/** One category in the mobile list: a tap target into its detail screen plus the two actions. */
function CategoryRow({ category, onEdit, onDelete }: CategoryRowProps) {
  const color = category.color || DEFAULT_CATEGORY_COLOR;

  return (
    <div className="flex items-center gap-2 bg-card border border-white/5 rounded-3xl px-3 py-2">
      <Link
        href={`${MOBILE_PATH_PREFIX}/categories/${category.id}`}
        aria-label={`Open ${category.name}`}
        style={{ minHeight: TAP_TARGET_PX }}
        className="flex items-center gap-3 min-w-0 flex-1"
      >
        <span
          className="w-9 h-9 rounded-2xl flex items-center justify-center shrink-0"
          style={{ backgroundColor: `${color}1f` }}
        >
          <span className="w-3 h-3 rounded-full" style={{ backgroundColor: color }} />
        </span>
        <span className="min-w-0">
          <span className="block text-[15px] font-medium text-text-primary truncate">
            {category.name}
          </span>
          <span className="block text-xs text-text-disabled truncate">
            {category.fields.length} fields · {DISPLAY_MODE_LABELS[category.display_mode]}
            {category.group ? ` · ${category.group}` : ''}
            {category.is_active ? '' : ' · Inactive'}
          </span>
        </span>
        <ChevronRight className="w-4 h-4 text-text-disabled shrink-0 ml-auto" strokeWidth={2} />
      </Link>
      <button
        onClick={onEdit}
        aria-label={`Edit ${category.name}`}
        style={{ minHeight: TAP_TARGET_PX, minWidth: TAP_TARGET_PX }}
        className="inline-flex items-center justify-center rounded-full text-text-secondary transition-colors duration-200 active:text-lime"
      >
        <Pencil className="w-4 h-4" strokeWidth={2} />
      </button>
      <button
        onClick={onDelete}
        aria-label={`Delete ${category.name}`}
        style={{ minHeight: TAP_TARGET_PX, minWidth: TAP_TARGET_PX }}
        className="inline-flex items-center justify-center rounded-full text-text-secondary transition-colors duration-200 active:text-danger"
      >
        <Trash2 className="w-4 h-4" strokeWidth={2} />
      </button>
    </div>
  );
}

interface CategoryEditorSheetProps {
  state: SheetState;
  onCancel: () => void;
  onSaved: () => void;
}

/**
 * The category editor itself: the sheet supplies the chrome, useCategoryDraft
 * the state and the save.
 *
 * Every control gets its own row. The desktop modal pairs Display/Streak mode
 * and Colour/Active in a `grid-cols-2`, which on a phone is two unusable
 * half-width controls — the single complaint this screen exists to fix.
 */
function CategoryEditorSheet({ state, onCancel, onSaved }: CategoryEditorSheetProps) {
  const editing = state.kind === 'edit' ? state.category : null;
  const draft = useCategoryDraft({ category: editing, onSaved });

  return (
    <FullScreenSheet
      title={editing ? editing.name : NEW_CATEGORY_SHEET_TITLE}
      onCancel={onCancel}
      onDone={() => void draft.save()}
      busy={draft.saving}
      error={draft.error}
      onDismissError={draft.dismissError}
    >
      <div>
        <label
          htmlFor="category-name"
          className="block text-[13px] font-medium text-text-secondary mb-2"
        >
          Name *
        </label>
        <input
          id="category-name"
          type="text"
          value={draft.name}
          onChange={(e) => draft.setName(e.target.value)}
          required
          style={{ minHeight: TAP_TARGET_PX }}
          className={entryInputClass}
        />
      </div>

      <div>
        <label
          htmlFor="category-description"
          className="block text-[13px] font-medium text-text-secondary mb-2"
        >
          Description
        </label>
        <textarea
          id="category-description"
          value={draft.description}
          onChange={(e) => draft.setDescription(e.target.value)}
          rows={3}
          className={entryInputClass}
        />
      </div>

      <div>
        <label
          htmlFor="category-display-mode"
          className="block text-[13px] font-medium text-text-secondary mb-2"
        >
          Display mode
        </label>
        <select
          id="category-display-mode"
          value={draft.displayMode}
          onChange={(e) => draft.setDisplayMode(e.target.value as CategoryDisplayMode)}
          style={{ minHeight: TAP_TARGET_PX }}
          className={entryInputClass}
        >
          <option value="form">{DISPLAY_MODE_LABELS.form}</option>
          <option value="checklist">{DISPLAY_MODE_LABELS.checklist}</option>
        </select>
        {draft.checklistNeedsBoolean && (
          <p className="text-[13px] text-warning mt-2">
            Checklist needs at least one boolean field — add one below or the save will be
            rejected.
          </p>
        )}
      </div>

      <div>
        <label
          htmlFor="category-streak-mode"
          className="block text-[13px] font-medium text-text-secondary mb-2"
        >
          Streak mode
        </label>
        <select
          id="category-streak-mode"
          value={draft.streakMode}
          onChange={(e) => draft.setStreakMode(e.target.value as CategoryStreakMode)}
          style={{ minHeight: TAP_TARGET_PX }}
          className={entryInputClass}
        >
          <option value="build">{STREAK_MODE_LABELS.build}</option>
          <option value="avoid">{STREAK_MODE_LABELS.avoid}</option>
        </select>
      </div>

      <div>
        <label
          htmlFor="category-show-in-today"
          className="block text-[13px] font-medium text-text-secondary mb-2"
        >
          {SHOW_IN_TODAY_LABEL}
        </label>
        <select
          id="category-show-in-today"
          value={showInTodayChoice(draft.showInToday)}
          onChange={(e) =>
            draft.setShowInToday(showInTodayValue(e.target.value as ShowInTodayChoice))
          }
          style={{ minHeight: TAP_TARGET_PX }}
          className={entryInputClass}
        >
          <option value="auto">{SHOW_IN_TODAY_LABELS.auto}</option>
          <option value="always">{SHOW_IN_TODAY_LABELS.always}</option>
          <option value="never">{SHOW_IN_TODAY_LABELS.never}</option>
        </select>
        <p className="text-[13px] text-text-disabled mt-2">
          Automatic shows the category when it has a number field to log against.
        </p>
      </div>

      <div>
        <label
          htmlFor="category-group"
          className="block text-[13px] font-medium text-text-secondary mb-2"
        >
          Group
        </label>
        <input
          id="category-group"
          type="text"
          value={draft.group}
          onChange={(e) => draft.setGroup(e.target.value)}
          placeholder="e.g. Health"
          maxLength={100}
          style={{ minHeight: TAP_TARGET_PX }}
          className={entryInputClass}
        />
      </div>

      <div>
        <label
          htmlFor="category-color"
          className="block text-[13px] font-medium text-text-secondary mb-2"
        >
          Color
        </label>
        <input
          id="category-color"
          type="color"
          value={draft.color}
          onChange={(e) => draft.setColor(e.target.value)}
          style={{ minHeight: TAP_TARGET_PX }}
          className="w-full h-12 bg-surface border border-white/10 rounded-2xl cursor-pointer p-1.5"
        />
      </div>

      <label
        style={{ minHeight: TAP_TARGET_PX }}
        className="flex items-center gap-3 cursor-pointer"
      >
        <input
          type="checkbox"
          checked={draft.isActive}
          onChange={(e) => draft.setIsActive(e.target.checked)}
          className="w-5 h-5 accent-[#B8FF36] rounded"
        />
        <span className="text-sm font-medium text-text-primary">Active</span>
      </label>

      <div>
        <p className="text-[13px] font-medium text-text-secondary mb-3">Fields</p>
        <div className="space-y-3">
          {draft.fields.map((field, index) => (
            <FieldCard
              // Index-keyed on purpose: a new row has no id yet, and the list is
              // only ever appended to or filtered, never reordered.
              key={index}
              field={field}
              position={index + 1}
              onChange={(updates) => draft.updateField(index, updates)}
              onRemove={() => draft.removeField(index)}
            />
          ))}
        </div>

        {/* Add field lives at the bottom: with many fields you don't scroll back
            up to add one more. */}
        <button
          type="button"
          onClick={draft.addField}
          style={{ minHeight: TAP_TARGET_PX }}
          className="mt-3 w-full inline-flex items-center justify-center gap-1.5 px-4 py-3 border border-dashed border-white/15 rounded-2xl text-sm text-lime font-medium transition-transform duration-200 active:scale-95"
        >
          <Plus className="w-4 h-4" strokeWidth={2} />
          Add field
        </button>
      </div>
    </FullScreenSheet>
  );
}

interface FieldCardProps {
  field: FieldCreate;
  /** 1-based position, used for the accessible names of the row's controls. */
  position: number;
  onChange: (updates: Partial<FieldCreate>) => void;
  onRemove: () => void;
}

/** One field of the category, stacked: name, type, options, required, remove. */
function FieldCard({ field, position, onChange, onRemove }: FieldCardProps) {
  return (
    <div className="bg-surface border border-white/5 rounded-2xl p-3 space-y-3">
      <input
        type="text"
        aria-label={`Field ${position} name`}
        placeholder="Field name"
        value={field.name}
        onChange={(e) => onChange({ name: e.target.value })}
        style={{ minHeight: TAP_TARGET_PX }}
        className={entryInputClass}
      />
      <select
        aria-label={`Field ${position} type`}
        value={field.field_type}
        onChange={(e) => onChange({ field_type: e.target.value as FieldCreate['field_type'] })}
        style={{ minHeight: TAP_TARGET_PX }}
        className={entryInputClass}
      >
        {(Object.keys(FIELD_TYPE_LABELS) as FieldCreate['field_type'][]).map((type) => (
          <option key={type} value={type}>
            {FIELD_TYPE_LABELS[type]}
          </option>
        ))}
      </select>

      {field.field_type === 'select' && (
        <input
          type="text"
          aria-label={`Field ${position} options`}
          placeholder="Options (comma separated)"
          value={field.options || ''}
          onChange={(e) => onChange({ options: e.target.value })}
          style={{ minHeight: TAP_TARGET_PX }}
          className={entryInputClass}
        />
      )}

      <div className="flex items-center justify-between gap-3">
        <label
          style={{ minHeight: TAP_TARGET_PX }}
          className="flex items-center gap-2 cursor-pointer"
        >
          <input
            type="checkbox"
            checked={field.is_required ?? false}
            onChange={(e) => onChange({ is_required: e.target.checked })}
            className="w-5 h-5 accent-[#B8FF36] rounded"
          />
          <span className="text-sm text-text-secondary">Required</span>
        </label>
        <button
          type="button"
          onClick={onRemove}
          aria-label={`Remove field ${position}`}
          style={{ minHeight: TAP_TARGET_PX, minWidth: TAP_TARGET_PX }}
          className="inline-flex items-center justify-center text-danger text-sm font-medium transition-transform duration-200 active:scale-95"
        >
          Remove
        </button>
      </div>
    </div>
  );
}
