'use client';
// [review:need-review] PHASE-01/44-mobile-journal
// summary: mobile Journal screen — same data as the desktop page via useJournal, entries rendered with the shared Markdown component, creation and editing done in a FullScreenSheet; all body text stays at text-sm or larger so it reads without a zoom

import { useState } from 'react';
import { BookOpen, Pencil, Plus, X } from 'lucide-react';
import ErrorAlert from '@/components/ErrorAlert';
import LoadingSpinner from '@/components/LoadingSpinner';
import Markdown from '@/components/Markdown';
import FullScreenSheet from '@/components/mobile/FullScreenSheet';
import { MOOD_OPTIONS, moodOption } from '@/components/journal-moods';
import { useJournal } from '@/hooks/useJournal';
import { journalAPI, type JournalEntry, type JournalEntryCreate } from '@/lib/api';
import { todayISO } from '@/lib/date';
import { TAP_TARGET_PX, entryInputClass } from '@/lib/ui-constants';

/** What the editor sheet is currently doing; closed when null. */
type SheetState = { kind: 'create' } | { kind: 'edit'; entry: JournalEntry };

/**
 * Accessible name of the FAB and title of the sheet it opens.
 *
 * Deliberately different from the sheet title so a button and a dialog do not
 * share a name in the accessibility tree.
 */
const NEW_ENTRY_BUTTON_LABEL = 'New journal entry';
const NEW_ENTRY_SHEET_TITLE = 'New entry';

export default function MobileJournalPage() {
  const { entries, loading, error, setError, reload } = useJournal();
  const [sheet, setSheet] = useState<SheetState | null>(null);

  const handleDelete = async (entry: JournalEntry) => {
    if (!confirm('Delete this journal entry?')) return;
    try {
      await journalAPI.delete(entry.id);
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete journal entry');
    }
  };

  if (loading) return <LoadingSpinner size="lg" />;

  // The page-level banner reports what happened to the list itself — a failed
  // load or delete. A failed save belongs inside the sheet, where the user is.
  const listError = error && <ErrorAlert message={error} onDismiss={() => setError(null)} />;

  return (
    <div className="space-y-5 animate-fade-rise">
      {listError}

      {entries.length === 0 ? (
        <div className="text-center py-12 bg-card border border-white/5 rounded-3xl">
          <div className="inline-flex p-4 rounded-3xl bg-surface mb-4">
            <BookOpen className="w-7 h-7 text-text-disabled" strokeWidth={2} />
          </div>
          <h2 className="text-base font-medium text-text-primary mb-1">Nothing here yet</h2>
          <p className="text-sm text-text-secondary px-6">
            Tap the plus button to write your first entry
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {entries.map((entry) => (
            <JournalCard
              key={entry.id}
              entry={entry}
              onEdit={() => setSheet({ kind: 'edit', entry })}
              onDelete={() => handleDelete(entry)}
            />
          ))}
        </div>
      )}

      <button
        onClick={() => setSheet({ kind: 'create' })}
        aria-label={NEW_ENTRY_BUTTON_LABEL}
        style={{ minHeight: TAP_TARGET_PX, minWidth: TAP_TARGET_PX }}
        className="fixed bottom-20 right-5 z-40 p-4 bg-lime text-background rounded-full shadow-[0_8px_24px_rgba(0,0,0,0.45)] transition-transform duration-200 active:scale-95"
      >
        <Plus className="w-6 h-6" strokeWidth={2.5} />
      </button>

      {sheet && (
        <JournalEditorSheet
          // Remounting per target keeps the draft trivially correct: a freshly
          // opened sheet never inherits the previous entry's values.
          key={sheet.kind === 'edit' ? sheet.entry.id : 'new'}
          entry={sheet.kind === 'edit' ? sheet.entry : null}
          onCancel={() => setSheet(null)}
          onSaved={async () => {
            setSheet(null);
            await reload();
          }}
        />
      )}
    </div>
  );
}

interface JournalCardProps {
  entry: JournalEntry;
  onEdit: () => void;
  onDelete: () => void;
}

/** One entry in the mobile list: date, mood, title, its rendered content and tags. */
function JournalCard({ entry, onEdit, onDelete }: JournalCardProps) {
  const mood = moodOption(entry.mood);
  const MoodIcon = mood?.icon ?? BookOpen;

  return (
    <div className="bg-card border border-white/5 rounded-3xl p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-3 min-w-0">
          <div className="w-10 h-10 rounded-2xl bg-surface flex items-center justify-center flex-shrink-0">
            <MoodIcon className={`w-5 h-5 ${mood?.color ?? 'text-text-disabled'}`} strokeWidth={2} />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-medium uppercase tracking-widest text-lime">
              {entry.entry_date}
            </p>
            <h3 className="text-base font-medium text-text-primary mt-0.5 truncate">
              {entry.title}
            </h3>
          </div>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={onEdit}
            aria-label="Edit journal entry"
            style={{ minHeight: TAP_TARGET_PX, minWidth: TAP_TARGET_PX }}
            className="inline-flex items-center justify-center rounded-full text-text-secondary transition-colors duration-200 active:text-lime"
          >
            <Pencil className="w-4 h-4" strokeWidth={2} />
          </button>
          <button
            onClick={onDelete}
            aria-label="Delete journal entry"
            style={{ minHeight: TAP_TARGET_PX, minWidth: TAP_TARGET_PX }}
            className="inline-flex items-center justify-center rounded-full text-text-secondary transition-colors duration-200 active:text-danger"
          >
            <X className="w-4 h-4" strokeWidth={2} />
          </button>
        </div>
      </div>

      <div className="mt-3">
        <Markdown content={entry.content} />
      </div>

      {entry.tags && (
        <div className="mt-3 flex flex-wrap gap-2">
          {entry.tags
            .split(',')
            .map((tag) => tag.trim())
            .filter(Boolean)
            .map((tag, idx) => (
              <span
                key={idx}
                className="px-3 py-1 bg-lime/10 text-lime rounded-full text-sm font-medium"
              >
                {tag}
              </span>
            ))}
        </div>
      )}
    </div>
  );
}

interface JournalEditorSheetProps {
  /** Entry being edited. Absent means the sheet creates a new one. */
  entry: JournalEntry | null;
  onCancel: () => void;
  onSaved: () => void;
}

/** The journal editor of the mobile shell: the sheet supplies the chrome, this holds the draft. */
function JournalEditorSheet({ entry, onCancel, onSaved }: JournalEditorSheetProps) {
  const [title, setTitle] = useState(entry?.title ?? '');
  const [content, setContent] = useState(entry?.content ?? '');
  const [entryDate, setEntryDate] = useState(entry?.entry_date ?? todayISO());
  const [mood, setMood] = useState(entry?.mood ?? '');
  const [tags, setTags] = useState(entry?.tags ?? '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const data: JournalEntryCreate = {
        title,
        content,
        entry_date: entryDate,
        mood: mood || undefined,
        tags: tags || undefined,
      };
      if (entry) {
        await journalAPI.update(entry.id, data);
      } else {
        await journalAPI.create(data);
      }
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save journal entry');
    } finally {
      setSaving(false);
    }
  };

  return (
    <FullScreenSheet
      title={entry ? 'Edit entry' : NEW_ENTRY_SHEET_TITLE}
      onCancel={onCancel}
      onDone={() => void save()}
      busy={saving}
      error={error}
      onDismissError={() => setError(null)}
    >
      <div>
        <label htmlFor="journal-title" className="block text-sm font-medium text-text-secondary mb-2">
          Title *
        </label>
        <input
          id="journal-title"
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          required
          placeholder="Give your entry a title..."
          style={{ minHeight: TAP_TARGET_PX }}
          className={entryInputClass}
        />
      </div>

      <div>
        <label htmlFor="journal-date" className="block text-sm font-medium text-text-secondary mb-2">
          Date *
        </label>
        <input
          id="journal-date"
          type="date"
          value={entryDate}
          onChange={(e) => setEntryDate(e.target.value)}
          required
          style={{ minHeight: TAP_TARGET_PX }}
          className={entryInputClass}
        />
      </div>

      <div>
        <span className="block text-sm font-medium text-text-secondary mb-3">
          How are you feeling?
        </span>
        <div className="flex flex-wrap gap-3">
          {MOOD_OPTIONS.map(({ value, label, icon: Icon, color }) => {
            const isSelected = mood === value;
            return (
              <button
                key={value}
                type="button"
                onClick={() => setMood(isSelected ? '' : value)}
                aria-pressed={isSelected}
                title={label}
                style={{ minHeight: TAP_TARGET_PX, minWidth: TAP_TARGET_PX }}
                className={`w-14 h-14 rounded-full flex items-center justify-center border transition-colors duration-200 ${
                  isSelected
                    ? 'border-lime bg-lime/10 shadow-[0_0_16px_rgba(184,255,54,0.3)]'
                    : 'border-white/10 bg-surface active:border-white/25'
                }`}
              >
                <Icon className={`w-6 h-6 ${color}`} strokeWidth={2} />
              </button>
            );
          })}
        </div>
      </div>

      <div>
        <label htmlFor="journal-content" className="block text-sm font-medium text-text-secondary mb-2">
          Content *
        </label>
        <textarea
          id="journal-content"
          value={content}
          onChange={(e) => setContent(e.target.value)}
          required
          rows={10}
          placeholder="What's on your mind today?"
          className={`${entryInputClass} resize-none`}
        />
      </div>

      <div>
        <label htmlFor="journal-tags" className="block text-sm font-medium text-text-secondary mb-2">
          Tags
        </label>
        <input
          id="journal-tags"
          type="text"
          value={tags}
          onChange={(e) => setTags(e.target.value)}
          placeholder="work, health, personal (comma separated)"
          style={{ minHeight: TAP_TARGET_PX }}
          className={entryInputClass}
        />
      </div>
    </FullScreenSheet>
  );
}
