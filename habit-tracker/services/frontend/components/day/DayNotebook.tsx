'use client';
// [review:need-review] PHASE-03/88
// summary: the day's notebook — one textarea whose text replaces the stored one, saved by an explicit button so a half-written sentence is never what the day keeps

import { useEffect, useState } from 'react';

/** The heading above the field. */
export const NOTEBOOK_TITLE = 'Блокнот дня';

/** Said in an empty field: what the notebook is for. */
export const NOTEBOOK_PLACEHOLDER =
  'Что случилось вместо плана, что мешало, что стоит помнить завтра';

export const NOTEBOOK_SAVE = 'Сохранить';
export const NOTEBOOK_SAVED = 'Сохранено';
export const NOTEBOOK_SAVE_ERROR = 'Блокнот не сохранился';

export interface DayNotebookProps {
  /** The stored text, or null when nothing has been written yet. */
  value: string | null;
  /** Writes the whole text; resolves when the day has it. */
  onSave: (content: string) => Promise<void>;
  compact?: boolean;
}

/**
 * The free text of a day.
 *
 * Saved by a button rather than on every keystroke: the text replaces what is
 * stored, and a per-keystroke save would mean the day's record is whatever the
 * writer happened to have typed when the network was quickest. It is also the
 * one place in the day screen where a person writes prose, and prose is written
 * in pauses.
 */
export default function DayNotebook({
  value,
  onSave,
  compact = false,
}: DayNotebookProps) {
  const [draft, setDraft] = useState(value ?? '');
  // What the day is known to hold: the text that arrived, or the last text this
  // field successfully saved. Kept apart from `value` because the parent does
  // not re-read the day after a save — without it a saved note would go on
  // reading as unsaved, and the button would stay lit over nothing.
  const [stored, setStored] = useState(value ?? '');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // A re-read of the day replaces both; the dirty flag below is what keeps an
  // unsaved sentence from being counted as stored.
  useEffect(() => {
    setDraft(value ?? '');
    setStored(value ?? '');
    setSaved(false);
  }, [value]);

  const dirty = draft !== stored;

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await onSave(draft);
      setStored(draft);
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : NOTEBOOK_SAVE_ERROR);
    } finally {
      setSaving(false);
    }
  };

  return (
    <section
      className={`bg-card border border-white/5 rounded-3xl ${
        compact ? 'p-4' : 'p-6'
      }`}
    >
      <h2
        className={`font-semibold text-text-primary ${
          compact ? 'text-base' : 'text-xl'
        }`}
      >
        {NOTEBOOK_TITLE}
      </h2>

      <textarea
        value={draft}
        aria-label={NOTEBOOK_TITLE}
        placeholder={NOTEBOOK_PLACEHOLDER}
        rows={compact ? 5 : 8}
        onChange={(event) => {
          setDraft(event.target.value);
          setSaved(false);
        }}
        className={`mt-3 w-full bg-surface rounded-2xl px-4 py-3 text-text-primary placeholder:text-text-disabled ${
          compact ? 'text-sm' : ''
        }`}
      />

      <div className="mt-3 flex items-center gap-3">
        <button
          type="button"
          disabled={saving || !dirty}
          onClick={() => void save()}
          className="rounded-2xl bg-surface px-4 py-2 text-text-primary disabled:opacity-50"
        >
          {NOTEBOOK_SAVE}
        </button>
        {saved && !dirty && (
          <span className="text-sm text-text-secondary">{NOTEBOOK_SAVED}</span>
        )}
        {error && <span className="text-sm text-warning">{error}</span>}
      </div>
    </section>
  );
}
