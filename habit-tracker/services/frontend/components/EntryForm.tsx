'use client';
// [review:need-review] PHASE-01/41-mobile-entries-fullscreen-sheet
// summary: desktop entry-creation modal; draft state, payload conversion and saving now come from useEntryDraft, so the markup is all that is left here

import { X } from 'lucide-react';
import { Category } from '@/lib/api';
import { FieldValueInput } from '@/components/FieldValueInput';
import ErrorAlert from '@/components/ErrorAlert';
import { useEntryDraft } from '@/hooks/useEntryDraft';
import { entryInputClass } from '@/lib/ui-constants';

export interface EntryFormProps {
  categories: Category[];
  onClose: () => void;
  onSuccess: () => void;
  /** Pin the form to one category and hide the picker (quick-add from a category page). */
  lockedCategoryId?: number;
  /** Prefill the entry date (e.g. the table cell's day); defaults to today. */
  date?: string;
}

export default function EntryForm({
  categories,
  onClose,
  onSuccess,
  lockedCategoryId,
  date,
}: EntryFormProps) {
  const draft = useEntryDraft({
    categories,
    categoryId: lockedCategoryId,
    date,
    onSaved: onSuccess,
  });
  const selectedCategory = draft.category;
  const categoryLocked = lockedCategoryId !== undefined;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    void draft.save();
  };

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4 z-50">
      <div className="bg-card border border-white/10 rounded-3xl max-w-2xl w-full max-h-[90vh] overflow-y-auto animate-fade-rise">
        <div className="sticky top-0 bg-card border-b border-white/5 px-6 py-5 flex justify-between items-center rounded-t-3xl">
          <h2 className="text-[22px] font-semibold text-text-primary">
            {categoryLocked && selectedCategory
              ? `New ${selectedCategory.name} entry`
              : 'New entry'}
          </h2>
          <button
            onClick={onClose}
            aria-label="Close"
            className="p-2 rounded-full text-text-secondary hover:text-text-primary hover:bg-white/5 transition-colors duration-200"
          >
            <X className="w-5 h-5" strokeWidth={2} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-6">
          {draft.error && <ErrorAlert message={draft.error} onDismiss={draft.dismissError} />}

          {!categoryLocked && (
            <div>
              <label className="block text-[13px] font-medium text-text-secondary mb-2">
                Category *
              </label>
              <select
                value={draft.categoryId}
                onChange={(e) => draft.setCategoryId(Number(e.target.value))}
                required
                className={entryInputClass}
              >
                {categories.map((cat) => (
                  <option key={cat.id} value={cat.id}>
                    {cat.name}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div>
            <label className="block text-[13px] font-medium text-text-secondary mb-2">
              Date *
            </label>
            <input
              type="date"
              value={draft.entryDate}
              onChange={(e) => draft.setEntryDate(e.target.value)}
              required
              className={entryInputClass}
            />
          </div>

          {selectedCategory && (
            <div className="space-y-4">
              <h3 className="text-lg font-medium text-text-primary">Field values</h3>
              {selectedCategory.fields.map((field) => (
                <div key={field.id}>
                  <label className="block text-[13px] font-medium text-text-secondary mb-2">
                    {field.name} {field.is_required && '*'}
                  </label>

                  <FieldValueInput
                    field={field}
                    value={draft.values[field.id] || ''}
                    onChange={(value) => draft.setValue(field.id, value)}
                  />
                </div>
              ))}
            </div>
          )}

          <div>
            <label className="block text-[13px] font-medium text-text-secondary mb-2">
              Notes
            </label>
            <textarea
              value={draft.notes}
              onChange={(e) => draft.setNotes(e.target.value)}
              rows={3}
              className={entryInputClass}
            />
          </div>

          <div className="flex gap-3 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-3 bg-surface border border-white/10 text-text-primary rounded-3xl font-medium transition-colors duration-200 hover:bg-white/5"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={draft.saving}
              className="flex-1 px-4 py-3 bg-lime text-background rounded-3xl font-medium transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_0_24px_rgba(184,255,54,0.35)] disabled:opacity-50 disabled:hover:translate-y-0 disabled:hover:shadow-none"
            >
              {draft.saving ? 'Creating...' : 'Create entry'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
