'use client';
// [review:need-review] PHASE-01/41-mobile-entries-fullscreen-sheet, PHASE-01/42-mobile-categories-and-detail
// summary: reusable entry card — draft state and saving come from useEntryDraft, value labelling from lib/entry-values, field inputs from components/FieldValueInput, colour fallback from lib/ui-constants

import { useState } from 'react';
import { Pencil, X } from 'lucide-react';
import { Category, Entry, entriesAPI } from '@/lib/api';
import { labelledValues } from '@/lib/entry-values';
import { DEFAULT_CATEGORY_COLOR, entryInputClass } from '@/lib/ui-constants';
import { useEntryDraft } from '@/hooks/useEntryDraft';
import ErrorAlert from '@/components/ErrorAlert';
import { FieldValueInput } from '@/components/FieldValueInput';

interface EntryCardProps {
  entry: Entry;
  category: Category | undefined;
  /** Called after a successful update or delete so the parent can reload data. */
  onMutated: () => void;
  onError: (message: string) => void;
}

/** Dark card for one entry: field values grid, notes, inline edit form, delete. */
export default function EntryCard({ entry, category, onMutated, onError }: EntryCardProps) {
  const [editing, setEditing] = useState(false);

  const categoryColor = category?.color || DEFAULT_CATEGORY_COLOR;

  const handleDelete = async () => {
    if (!confirm('Delete this entry?')) return;
    try {
      await entriesAPI.delete(entry.id);
      onMutated();
    } catch (err) {
      onError(err instanceof Error ? err.message : 'Failed to delete entry');
    }
  };

  return (
    <div className="bg-card border border-white/5 rounded-3xl p-6 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_10px_30px_rgba(0,0,0,0.5)]">
      <div className="flex justify-between items-start mb-4">
        <div className="flex items-center gap-3 min-w-0">
          <div
            className="w-10 h-10 rounded-2xl flex items-center justify-center flex-shrink-0"
            style={{ backgroundColor: `${categoryColor}1f` }}
          >
            <span
              className="w-3.5 h-3.5 rounded-full"
              style={{ backgroundColor: categoryColor }}
            />
          </div>
          <h3 className="text-lg font-medium text-text-primary truncate">
            {category?.name || 'Unknown Category'}
          </h3>
        </div>
        <div className="flex items-center gap-1 flex-shrink-0">
          {category && !editing && (
            <button
              onClick={() => setEditing(true)}
              aria-label="Edit entry"
              className="p-2 rounded-full text-text-secondary hover:text-lime hover:bg-lime/10 transition-colors duration-200"
            >
              <Pencil className="w-4 h-4" strokeWidth={2} />
            </button>
          )}
          <button
            onClick={handleDelete}
            aria-label="Delete entry"
            className="p-2 rounded-full text-text-secondary hover:text-danger hover:bg-danger/10 transition-colors duration-200"
          >
            <X className="w-4 h-4" strokeWidth={2} />
          </button>
        </div>
      </div>

      {editing && category ? (
        <EntryEditForm
          entry={entry}
          category={category}
          onCancel={() => setEditing(false)}
          onSaved={() => {
            setEditing(false);
            onMutated();
          }}
        />
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {labelledValues(category, entry).map(({ id, label, value }) => (
              <div key={id} className="bg-surface border border-white/5 rounded-2xl p-3.5">
                <p className="text-xs text-text-disabled mb-1">{label}</p>
                <p className="text-sm font-medium text-text-primary break-words">{value}</p>
              </div>
            ))}
          </div>

          {entry.notes && (
            <div className="mt-4 pt-4 border-t border-white/5">
              <p className="text-sm text-text-secondary">{entry.notes}</p>
            </div>
          )}
        </>
      )}
    </div>
  );
}

interface EntryEditFormProps {
  entry: Entry;
  category: Category;
  onCancel: () => void;
  onSaved: () => void;
}

/**
 * The card's inline editor. Mounted only while editing, so its draft is seeded
 * from the entry as it stands when the pencil is clicked and a later reload of
 * the list cannot overwrite what the user has typed.
 */
function EntryEditForm({ entry, category, onCancel, onSaved }: EntryEditFormProps) {
  const draft = useEntryDraft({ categories: [category], entry, onSaved });

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        void draft.save();
      }}
      className="space-y-4"
    >
      {draft.error && <ErrorAlert message={draft.error} onDismiss={draft.dismissError} />}

      <div>
        <label className="block text-[13px] font-medium text-text-secondary mb-2">Date *</label>
        <input
          type="date"
          value={draft.entryDate}
          onChange={(e) => draft.setEntryDate(e.target.value)}
          required
          className={entryInputClass}
        />
      </div>

      {category.fields.map((field) => (
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

      <div>
        <label className="block text-[13px] font-medium text-text-secondary mb-2">Notes</label>
        <textarea
          value={draft.notes}
          onChange={(e) => draft.setNotes(e.target.value)}
          rows={3}
          className={entryInputClass}
        />
      </div>

      <div className="flex gap-3 pt-2">
        <button
          type="button"
          onClick={onCancel}
          className="flex-1 px-4 py-3 bg-surface border border-white/10 text-text-primary rounded-3xl font-medium transition-colors duration-200 hover:bg-white/5"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={draft.saving}
          className="flex-1 px-4 py-3 bg-lime text-background rounded-3xl font-medium transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_0_24px_rgba(184,255,54,0.35)] disabled:opacity-50 disabled:hover:translate-y-0 disabled:hover:shadow-none"
        >
          {draft.saving ? 'Saving...' : 'Save'}
        </button>
      </div>
    </form>
  );
}
