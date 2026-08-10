'use client';
// [review:need-review] PHASE-01/73-category-field-reorder
// summary: desktop Categories page — list/cards layout and the editor modal, whose field rows are keyed by draft row and reorderable through the shared FieldReorderButtons, with a live region announcing where a moved row landed; all of the state (load, layout preference, delete, form draft with the id-carrying field diff-sync) comes from hooks/useCategories, field order from lib/today-categories and the enum labels plus field styling from lib/ui-constants, all shared with /m/categories

import { useState } from 'react';
import Link from 'next/link';
import {
  type Category,
  type CategoryDisplayMode,
  type CategoryStreakMode,
  type FieldCreate,
} from '@/lib/api';
import LoadingSpinner from '@/components/LoadingSpinner';
import ErrorAlert from '@/components/ErrorAlert';
import FieldReorderButtons from '@/components/FieldReorderButtons';
import {
  DEFAULT_CATEGORY_COLOR,
  useCategories,
  useCategoryDraft,
  type DraftField,
  type FieldMoveDirection,
} from '@/hooks/useCategories';
import { orderedFields } from '@/lib/today-categories';
import {
  DISPLAY_MODE_LABELS,
  FIELD_TYPE_LABELS,
  SHOW_IN_TODAY_LABEL,
  SHOW_IN_TODAY_LABELS,
  STREAK_MODE_LABELS,
  compactInputClass,
  entryInputClass,
  showInTodayChoice,
  showInTodayValue,
  type ShowInTodayChoice,
} from '@/lib/ui-constants';
import {
  Plus,
  Pencil,
  Trash2,
  FolderKanban,
  X,
  LayoutGrid,
  List,
} from 'lucide-react';

export default function CategoriesPage() {
  const { categories, loading, error, setError, layout, setLayout, reload, remove } =
    useCategories();
  const [showForm, setShowForm] = useState(false);
  const [editingCategory, setEditingCategory] = useState<Category | null>(null);

  const openEdit = (category: Category) => {
    setEditingCategory(category);
    setShowForm(true);
  };

  const closeForm = () => {
    setShowForm(false);
    setEditingCategory(null);
  };

  const handleDelete = async (id: number) => {
    if (!confirm('Are you sure? This will delete all related entries!')) return;
    await remove(id);
  };

  if (loading) return <LoadingSpinner size="lg" />;

  return (
    <div className="space-y-8 animate-fade-rise">
      <div className="flex justify-between items-center gap-4">
        <div>
          <h1 className="text-4xl font-bold text-text-primary tracking-tight">
            Categories
            <span className="text-lime">.</span>
          </h1>
          <p className="mt-2 text-text-secondary">Manage your tracking categories</p>
        </div>
        <div className="flex items-center gap-3">
          {categories.length > 0 && (
            <div className="flex items-center gap-1 p-1 bg-surface border border-white/10 rounded-2xl">
              <button
                onClick={() => setLayout('cards')}
                aria-label="Card view"
                aria-pressed={layout === 'cards'}
                className={`p-2 rounded-xl transition-colors duration-200 ${
                  layout === 'cards'
                    ? 'bg-lime/15 text-lime'
                    : 'text-text-secondary hover:text-text-primary'
                }`}
              >
                <LayoutGrid className="w-4 h-4" strokeWidth={2} />
              </button>
              <button
                onClick={() => setLayout('list')}
                aria-label="List view"
                aria-pressed={layout === 'list'}
                className={`p-2 rounded-xl transition-colors duration-200 ${
                  layout === 'list'
                    ? 'bg-lime/15 text-lime'
                    : 'text-text-secondary hover:text-text-primary'
                }`}
              >
                <List className="w-4 h-4" strokeWidth={2} />
              </button>
            </div>
          )}
          <button
            onClick={() => {
              setEditingCategory(null);
              setShowForm(true);
            }}
            className="flex items-center gap-2 px-6 py-3 bg-lime text-background rounded-3xl font-medium transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_0_24px_rgba(184,255,54,0.35)]"
          >
            <Plus className="w-5 h-5" strokeWidth={2} />
            <span className="hidden sm:inline">New category</span>
          </button>
        </div>
      </div>

      {error && <ErrorAlert message={error} onDismiss={() => setError(null)} />}

      {/* Category Form Modal */}
      {showForm && (
        <CategoryForm
          // Remounting per target keeps the draft trivially correct: a freshly
          // opened modal never inherits the previous category's values.
          key={editingCategory?.id ?? 'new'}
          category={editingCategory}
          onClose={closeForm}
          onSuccess={() => {
            closeForm();
            void reload();
          }}
        />
      )}

      {/* Categories Grid */}
      {categories.length === 0 ? (
        <div className="text-center py-16 bg-card border border-white/5 rounded-3xl">
          <div className="inline-flex p-4 rounded-3xl bg-surface mb-4">
            <FolderKanban className="w-8 h-8 text-text-disabled" strokeWidth={2} />
          </div>
          <h3 className="text-lg font-medium text-text-primary mb-1">Nothing here yet</h3>
          <p className="text-text-secondary mb-6">Create your first category to start tracking</p>
          <button
            onClick={() => setShowForm(true)}
            className="px-6 py-3 bg-lime text-background rounded-3xl font-medium transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_0_24px_rgba(184,255,54,0.35)]"
          >
            Create category
          </button>
        </div>
      ) : layout === 'list' ? (
        <div className="space-y-2">
          {categories.map((category) => (
            <div
              key={category.id}
              className="flex items-center gap-3 bg-card border border-white/5 rounded-2xl px-4 py-3 transition-colors duration-200 hover:border-white/10"
            >
              <Link
                href={`/categories/${category.id}`}
                aria-label={`Open ${category.name} chart`}
                className="flex items-center gap-3 min-w-0 flex-1 group"
              >
                <span
                  className="w-8 h-8 rounded-xl flex items-center justify-center flex-shrink-0"
                  style={{ backgroundColor: `${category.color || DEFAULT_CATEGORY_COLOR}1f` }}
                >
                  <span
                    className="w-3 h-3 rounded-full"
                    style={{ backgroundColor: category.color || DEFAULT_CATEGORY_COLOR }}
                  />
                </span>
                <span className="min-w-0">
                  <span className="block text-text-primary font-medium truncate transition-colors duration-200 group-hover:text-lime">
                    {category.name}
                  </span>
                  <span className="block text-xs text-text-disabled truncate">
                    {category.fields.length} fields · {DISPLAY_MODE_LABELS[category.display_mode]}
                    {category.group ? ` · ${category.group}` : ''}
                    {category.is_active ? '' : ' · Inactive'}
                  </span>
                </span>
              </Link>
              <div className="flex gap-1 flex-shrink-0">
                <button
                  onClick={() => openEdit(category)}
                  aria-label="Edit category"
                  className="p-2 rounded-full text-text-secondary hover:text-lime hover:bg-lime/10 transition-colors duration-200"
                >
                  <Pencil className="w-4 h-4" strokeWidth={2} />
                </button>
                <button
                  onClick={() => void handleDelete(category.id)}
                  aria-label="Delete category"
                  className="p-2 rounded-full text-text-secondary hover:text-danger hover:bg-danger/10 transition-colors duration-200"
                >
                  <Trash2 className="w-4 h-4" strokeWidth={2} />
                </button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {categories.map((category) => (
            <div
              key={category.id}
              className="bg-card border border-white/5 rounded-3xl p-6 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_10px_30px_rgba(0,0,0,0.5)]"
            >
              <div className="flex justify-between items-start mb-4">
                <Link
                  href={`/categories/${category.id}`}
                  aria-label={`Open ${category.name} chart`}
                  className="flex items-center gap-3 min-w-0 group"
                >
                  <div
                    className="w-10 h-10 rounded-2xl flex items-center justify-center flex-shrink-0"
                    style={{ backgroundColor: `${category.color || DEFAULT_CATEGORY_COLOR}1f` }}
                  >
                    <span
                      className="w-3.5 h-3.5 rounded-full"
                      style={{ backgroundColor: category.color || DEFAULT_CATEGORY_COLOR }}
                    />
                  </div>
                  <h3 className="text-lg font-medium text-text-primary truncate transition-colors duration-200 group-hover:text-lime">
                    {category.name}
                  </h3>
                </Link>
                <div className="flex gap-1 flex-shrink-0">
                  <button
                    onClick={() => openEdit(category)}
                    aria-label="Edit category"
                    className="p-2 rounded-full text-text-secondary hover:text-lime hover:bg-lime/10 transition-colors duration-200"
                  >
                    <Pencil className="w-4 h-4" strokeWidth={2} />
                  </button>
                  <button
                    onClick={() => void handleDelete(category.id)}
                    aria-label="Delete category"
                    className="p-2 rounded-full text-text-secondary hover:text-danger hover:bg-danger/10 transition-colors duration-200"
                  >
                    <Trash2 className="w-4 h-4" strokeWidth={2} />
                  </button>
                </div>
              </div>

              {category.description && (
                <p className="text-text-secondary text-sm mb-4">{category.description}</p>
              )}

              <div className="space-y-2">
                <p className="text-[13px] font-medium text-text-secondary">
                  Fields ({category.fields.length})
                </p>
                {category.fields.length > 0 ? (
                  <ul className="space-y-1.5">
                    {orderedFields(category).map((field) => (
                      <li
                        key={field.id}
                        className="text-sm text-text-secondary flex items-center gap-2"
                      >
                        <span className="w-1.5 h-1.5 bg-lime rounded-full flex-shrink-0" />
                        <span className="text-text-primary">{field.name}</span>
                        <span className="text-text-disabled">{field.field_type}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-text-disabled">No fields yet</p>
                )}
              </div>

              <div className="mt-5 pt-4 border-t border-white/5 flex flex-wrap gap-2">
                <span
                  className={`inline-block px-3 py-1 rounded-full text-xs font-medium ${
                    category.is_active
                      ? 'bg-success/10 text-success'
                      : 'bg-white/5 text-text-disabled'
                  }`}
                >
                  {category.is_active ? 'Active' : 'Inactive'}
                </span>
                <span className="inline-block px-3 py-1 rounded-full text-xs font-medium bg-lime/10 text-lime">
                  {DISPLAY_MODE_LABELS[category.display_mode]}
                </span>
                {category.streak_mode === 'avoid' && (
                  <span className="inline-block px-3 py-1 rounded-full text-xs font-medium bg-danger/10 text-danger">
                    {STREAK_MODE_LABELS.avoid}
                  </span>
                )}
                {category.group && (
                  <span className="inline-block px-3 py-1 rounded-full text-xs font-medium bg-white/5 text-text-secondary">
                    {category.group}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

interface CategoryFormProps {
  category: Category | null;
  onClose: () => void;
  onSuccess: () => void;
}

function CategoryForm({ category, onClose, onSuccess }: CategoryFormProps) {
  const draft = useCategoryDraft({ category, onSaved: onSuccess });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    void draft.save();
  };

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4 z-50">
      <div className="bg-card border border-white/10 rounded-3xl max-w-2xl w-full max-h-[90vh] overflow-y-auto animate-fade-rise">
        <div className="sticky top-0 bg-card border-b border-white/5 px-6 py-5 flex justify-between items-center rounded-t-3xl">
          <h2 className="text-[22px] font-semibold text-text-primary">
            {category ? 'Edit category' : 'New category'}
          </h2>
          <button
            onClick={onClose}
            aria-label="Close"
            className="p-2 rounded-full text-text-secondary hover:text-text-primary hover:bg-white/5 transition-colors duration-200"
          >
            <X className="w-5 h-5" strokeWidth={2} />
          </button>
        </div>

        <form id="category-form" onSubmit={handleSubmit} className="p-6 space-y-6">
          {draft.error && <ErrorAlert message={draft.error} onDismiss={draft.dismissError} />}

          <div>
            <label className="block text-[13px] font-medium text-text-secondary mb-2">
              Name *
            </label>
            <input
              type="text"
              value={draft.name}
              onChange={(e) => draft.setName(e.target.value)}
              required
              className={entryInputClass}
            />
          </div>

          <div>
            <label className="block text-[13px] font-medium text-text-secondary mb-2">
              Description
            </label>
            <textarea
              value={draft.description}
              onChange={(e) => draft.setDescription(e.target.value)}
              rows={3}
              className={entryInputClass}
            />
          </div>

          {/* Two-up only once there is room for it: below `sm` a pair of
              half-width controls is unusable. */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-[13px] font-medium text-text-secondary mb-2">
                Display mode
              </label>
              <select
                value={draft.displayMode}
                onChange={(e) => draft.setDisplayMode(e.target.value as CategoryDisplayMode)}
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
              <label className="block text-[13px] font-medium text-text-secondary mb-2">
                Streak mode
              </label>
              <select
                value={draft.streakMode}
                onChange={(e) => draft.setStreakMode(e.target.value as CategoryStreakMode)}
                className={entryInputClass}
              >
                <option value="build">{STREAK_MODE_LABELS.build}</option>
                <option value="avoid">{STREAK_MODE_LABELS.avoid}</option>
              </select>
            </div>
          </div>

          <div>
            <label className="block text-[13px] font-medium text-text-secondary mb-2">
              Group
            </label>
            <input
              type="text"
              value={draft.group}
              onChange={(e) => draft.setGroup(e.target.value)}
              placeholder="e.g. Health"
              maxLength={100}
              className={entryInputClass}
            />
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

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-[13px] font-medium text-text-secondary mb-2">
                Color
              </label>
              <input
                type="color"
                value={draft.color}
                onChange={(e) => draft.setColor(e.target.value)}
                className="w-full h-12 bg-surface border border-white/10 rounded-2xl cursor-pointer p-1.5"
              />
            </div>

            <div className="flex items-end pb-2">
              <label className="flex items-center gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={draft.isActive}
                  onChange={(e) => draft.setIsActive(e.target.checked)}
                  className="w-4 h-4 accent-[#B8FF36] rounded"
                />
                <span className="text-sm font-medium text-text-primary">Active</span>
              </label>
            </div>
          </div>

          {/* Fields Section */}
          <div>
            <label className="block text-[13px] font-medium text-text-secondary mb-4">
              Fields
            </label>

            {/* The reorder is a purely visual event otherwise: the row swaps
                with its neighbour and nothing says so out loud. */}
            <p role="status" aria-live="polite" className="sr-only">
              {draft.moveAnnouncement}
            </p>

            <div className="space-y-4">
              {draft.fields.map((field, index) => (
                <FieldRow
                  // Keyed by the draft's own row key rather than the index: the
                  // rows reorder, and an index key would leave React reusing the
                  // DOM of whichever row used to sit here.
                  key={field.key}
                  field={field}
                  position={index + 1}
                  canMoveUp={index > 0}
                  canMoveDown={index < draft.fields.length - 1}
                  onChange={(updates) => draft.updateField(index, updates)}
                  onRemove={() => draft.removeField(index)}
                  onMove={(direction) => draft.moveField(index, direction)}
                />
              ))}
            </div>

            {/* Add field lives at the bottom: with many fields you don't scroll
                back up to add one more. */}
            <button
              type="button"
              onClick={draft.addField}
              className="mt-4 w-full inline-flex items-center justify-center gap-1.5 px-4 py-3 border border-dashed border-white/15 rounded-2xl text-sm text-lime hover:text-green-secondary hover:border-lime/40 font-medium transition-colors duration-200"
            >
              <Plus className="w-4 h-4" strokeWidth={2} />
              Add field
            </button>
          </div>
        </form>

        {/* Sticky footer so actions stay reachable without scrolling the whole modal. */}
        <div className="sticky bottom-0 bg-card border-t border-white/5 px-6 py-4 flex gap-3 rounded-b-3xl">
          <button
            type="button"
            onClick={onClose}
            className="flex-1 px-4 py-3 bg-surface border border-white/10 text-text-primary rounded-3xl font-medium transition-colors duration-200 hover:bg-white/5"
          >
            Cancel
          </button>
          <button
            type="submit"
            form="category-form"
            disabled={draft.saving}
            className="flex-1 px-4 py-3 bg-lime text-background rounded-3xl font-medium transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_0_24px_rgba(184,255,54,0.35)] disabled:opacity-50 disabled:hover:translate-y-0 disabled:hover:shadow-none"
          >
            {draft.saving ? 'Saving...' : category ? 'Update' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  );
}

interface FieldRowProps {
  /**
   * `DraftField`, not `FieldCreate`: the row's identity is part of the contract
   * between the editor and this component. The parent keys the row by
   * `field.key`, and a prop type that did not carry it would let a caller pass
   * a plain payload object whose rows React can only tell apart by position.
   */
  field: DraftField;
  /** 1-based position, used for the accessible names of the row's controls. */
  position: number;
  canMoveUp: boolean;
  canMoveDown: boolean;
  onChange: (updates: Partial<FieldCreate>) => void;
  onRemove: () => void;
  onMove: (direction: FieldMoveDirection) => void;
}

/** One field of the category in the desktop modal. */
function FieldRow({
  field,
  position,
  canMoveUp,
  canMoveDown,
  onChange,
  onRemove,
  onMove,
}: FieldRowProps) {
  return (
    <div className="bg-surface border border-white/5 rounded-2xl p-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-3">
        <input
          type="text"
          aria-label={`Field ${position} name`}
          placeholder="Field name"
          value={field.name}
          onChange={(e) => onChange({ name: e.target.value })}
          className={compactInputClass}
        />
        <select
          value={field.field_type}
          onChange={(e) => onChange({ field_type: e.target.value as FieldCreate['field_type'] })}
          className={compactInputClass}
        >
          {/* Driven by the shared label map, so a new field type on the API type
              shows up here instead of silently missing an option. */}
          {Object.entries(FIELD_TYPE_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>

      {field.field_type === 'select' && (
        <input
          type="text"
          placeholder="Options (comma separated)"
          value={field.options || ''}
          onChange={(e) => onChange({ options: e.target.value })}
          className={`${compactInputClass} mb-3`}
        />
      )}

      <div className="flex justify-between items-center">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={field.is_required ?? false}
            onChange={(e) => onChange({ is_required: e.target.checked })}
            className="w-4 h-4 accent-[#B8FF36] rounded"
          />
          <span className="text-sm text-text-secondary">Required</span>
        </label>
        <div className="flex items-center gap-2">
          <FieldReorderButtons
            position={position}
            canMoveUp={canMoveUp}
            canMoveDown={canMoveDown}
            onMove={onMove}
          />
          <button
            type="button"
            onClick={onRemove}
            aria-label={`Remove field ${position}`}
            className="text-danger hover:text-red-400 text-sm font-medium transition-colors duration-200"
          >
            Remove
          </button>
        </div>
      </div>
    </div>
  );
}
