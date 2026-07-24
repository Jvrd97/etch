'use client';
// [review:need-review] PHASE-01/44-mobile-journal
// summary: desktop /journal page — entries, loading, error and reload now come from useJournal, shared with /m/journal; markup unchanged

import { useState } from 'react';
import { journalAPI, JournalEntry, JournalEntryCreate } from '@/lib/api';
import { useJournal } from '@/hooks/useJournal';
import Markdown from '@/components/Markdown';
import { todayISO } from '@/lib/date';
import LoadingSpinner from '@/components/LoadingSpinner';
import ErrorAlert from '@/components/ErrorAlert';
import { Plus, BookOpen, X, Pencil, Trash2 } from 'lucide-react';
import { MOOD_OPTIONS } from '@/components/journal-moods';

const inputClass =
  'w-full px-4 py-3 bg-surface border border-white/10 rounded-2xl text-text-primary placeholder:text-text-disabled outline-none transition-all duration-200 focus:border-lime focus:ring-2 focus:ring-lime/25';

export default function JournalPage() {
  const { entries, loading, error, setError, reload } = useJournal();
  const [showForm, setShowForm] = useState(false);
  const [editingEntry, setEditingEntry] = useState<JournalEntry | null>(null);

  const handleDelete = async (id: number) => {
    if (!confirm('Delete this journal entry?')) return;
    try {
      await journalAPI.delete(id);
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete journal entry');
    }
  };

  if (loading) return <LoadingSpinner size="lg" />;

  return (
    <div className="space-y-8 animate-fade-rise">
      <div className="flex justify-between items-center gap-4">
        <div>
          <h1 className="text-4xl font-bold text-text-primary tracking-tight">
            Journal
            <span className="text-lime">.</span>
          </h1>
          <p className="mt-2 text-text-secondary">Capture your thoughts and feelings</p>
        </div>
        <button
          onClick={() => {
            setEditingEntry(null);
            setShowForm(true);
          }}
          className="flex items-center gap-2 px-6 py-3 bg-lime text-background rounded-3xl font-medium transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_0_24px_rgba(184,255,54,0.35)]"
        >
          <Plus className="w-5 h-5" strokeWidth={2} />
          <span className="hidden sm:inline">New entry</span>
        </button>
      </div>

      {error && <ErrorAlert message={error} onDismiss={() => setError(null)} />}

      {/* Journal Form Modal */}
      {showForm && (
        <JournalForm
          entry={editingEntry}
          onClose={() => {
            setShowForm(false);
            setEditingEntry(null);
          }}
          onSuccess={() => {
            setShowForm(false);
            setEditingEntry(null);
            void reload();
          }}
        />
      )}

      {/* Journal Entries timeline */}
      {entries.length === 0 ? (
        <div className="text-center py-16 bg-card border border-white/5 rounded-3xl">
          <div className="inline-flex p-4 rounded-3xl bg-surface mb-4">
            <BookOpen className="w-8 h-8 text-text-disabled" strokeWidth={2} />
          </div>
          <h3 className="text-lg font-medium text-text-primary mb-1">Nothing here yet</h3>
          <p className="text-text-secondary mb-6">Start writing about your day</p>
          <button
            onClick={() => setShowForm(true)}
            className="px-6 py-3 bg-lime text-background rounded-3xl font-medium transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_0_24px_rgba(184,255,54,0.35)]"
          >
            Write first entry
          </button>
        </div>
      ) : (
        <div className="space-y-5">
          {entries.map((entry) => {
            const moodInfo = MOOD_OPTIONS.find(m => m.value === entry.mood);
            const MoodIcon = moodInfo?.icon;

            return (
              <div
                key={entry.id}
                className="bg-card border border-white/5 rounded-3xl p-6 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_10px_30px_rgba(0,0,0,0.5)]"
              >
                <div className="flex justify-between items-start mb-4">
                  <div className="flex items-start gap-4 min-w-0">
                    <div className="w-11 h-11 rounded-2xl bg-surface flex items-center justify-center flex-shrink-0">
                      {MoodIcon ? (
                        <MoodIcon className={`w-5 h-5 ${moodInfo.color}`} strokeWidth={2} />
                      ) : (
                        <BookOpen className="w-5 h-5 text-text-disabled" strokeWidth={2} />
                      )}
                    </div>
                    <div className="min-w-0">
                      <p className="text-[13px] font-medium uppercase tracking-widest text-lime">
                        {entry.entry_date}
                      </p>
                      <h3 className="text-lg font-medium text-text-primary mt-1 truncate">
                        {entry.title}
                      </h3>
                    </div>
                  </div>
                  <div className="flex gap-1 flex-shrink-0">
                    <button
                      onClick={() => {
                        setEditingEntry(entry);
                        setShowForm(true);
                      }}
                      aria-label="Edit journal entry"
                      className="p-2 rounded-full text-text-secondary hover:text-lime hover:bg-lime/10 transition-colors duration-200"
                    >
                      <Pencil className="w-4 h-4" strokeWidth={2} />
                    </button>
                    <button
                      onClick={() => handleDelete(entry.id)}
                      aria-label="Delete journal entry"
                      className="p-2 rounded-full text-text-secondary hover:text-danger hover:bg-danger/10 transition-colors duration-200"
                    >
                      <Trash2 className="w-4 h-4" strokeWidth={2} />
                    </button>
                  </div>
                </div>

                <div className="mb-4">
                  <Markdown content={entry.content} />
                </div>

                {entry.tags && (
                  <div className="flex flex-wrap gap-2">
                    {entry.tags.split(',').map((tag, idx) => (
                      <span
                        key={idx}
                        className="px-3 py-1 bg-lime/10 text-lime rounded-full text-xs font-medium"
                      >
                        {tag.trim()}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

interface JournalFormProps {
  entry: JournalEntry | null;
  onClose: () => void;
  onSuccess: () => void;
}

function JournalForm({ entry, onClose, onSuccess }: JournalFormProps) {
  const [title, setTitle] = useState(entry?.title || '');
  const [content, setContent] = useState(entry?.content || '');
  const [entryDate, setEntryDate] = useState(
    entry?.entry_date || todayISO()
  );
  const [mood, setMood] = useState(entry?.mood || '');
  const [tags, setTags] = useState(entry?.tags || '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
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

      onSuccess();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save journal entry');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4 z-50">
      <div className="bg-card border border-white/10 rounded-3xl max-w-3xl w-full max-h-[90vh] overflow-y-auto animate-fade-rise">
        <div className="sticky top-0 bg-card border-b border-white/5 px-6 py-5 flex justify-between items-center rounded-t-3xl">
          <h2 className="text-[22px] font-semibold text-text-primary">
            {entry ? 'Edit entry' : 'New journal entry'}
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
          {error && <ErrorAlert message={error} />}

          <div>
            <label className="block text-[13px] font-medium text-text-secondary mb-2">
              Title *
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
              placeholder="Give your entry a title..."
              className={inputClass}
            />
          </div>

          <div>
            <label className="block text-[13px] font-medium text-text-secondary mb-2">
              Date *
            </label>
            <input
              type="date"
              value={entryDate}
              onChange={(e) => setEntryDate(e.target.value)}
              required
              className={inputClass}
            />
          </div>

          <div>
            <label className="block text-[13px] font-medium text-text-secondary mb-3">
              How are you feeling?
            </label>
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
                    className={`w-14 h-14 rounded-full flex items-center justify-center border transition-all duration-200 ${
                      isSelected
                        ? 'border-lime bg-lime/10 shadow-[0_0_16px_rgba(184,255,54,0.3)] scale-105'
                        : 'border-white/10 bg-surface hover:border-white/25'
                    }`}
                  >
                    <Icon className={`w-6 h-6 ${color}`} strokeWidth={2} />
                  </button>
                );
              })}
            </div>
            <p className="text-[13px] text-text-disabled mt-2">
              {mood ? MOOD_OPTIONS.find(m => m.value === mood)?.label : 'Tap a mood to select'}
            </p>
          </div>

          <div>
            <label className="block text-[13px] font-medium text-text-secondary mb-2">
              Content *
            </label>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              required
              rows={10}
              placeholder="What's on your mind today?"
              className={`${inputClass} resize-none`}
            />
            <p className="text-[13px] text-text-disabled mt-1">{content.length} characters</p>
          </div>

          <div>
            <label className="block text-[13px] font-medium text-text-secondary mb-2">
              Tags
            </label>
            <input
              type="text"
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="work, health, personal (comma separated)"
              className={inputClass}
            />
            {tags && (
              <div className="flex flex-wrap gap-2 mt-3">
                {tags
                  .split(',')
                  .map(t => t.trim())
                  .filter(Boolean)
                  .map((tag, idx) => (
                    <span
                      key={idx}
                      className="px-3 py-1 bg-lime/10 text-lime rounded-full text-xs font-medium"
                    >
                      {tag}
                    </span>
                  ))}
              </div>
            )}
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
              disabled={saving}
              className="flex-1 px-4 py-3 bg-lime text-background rounded-3xl font-medium transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_0_24px_rgba(184,255,54,0.35)] disabled:opacity-50 disabled:hover:translate-y-0 disabled:hover:shadow-none"
            >
              {saving ? 'Saving...' : entry ? 'Update' : 'Create'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
