'use client';
// [review:need-review] PHASE-01/41-mobile-entries-fullscreen-sheet
// summary: single owner of an entry draft (category, date, notes, values) and of its save — create or update, chosen by whether an entry is being edited; shared by EntryForm, EntryCard's inline editor and the mobile sheet

import { useCallback, useMemo, useRef, useState } from 'react';
import { entriesAPI, type Category, type Entry } from '@/lib/api';
import { todayISO } from '@/lib/date';
import { draftValuesFromEntry, toEntryValues, type EntryDraftValues } from '@/lib/entry-values';

/**
 * Text shown when the rejected save carries no message of its own.
 *
 * One string for all three editors: the desktop modal, the inline card editor
 * and the mobile sheet used to each invent their own wording for the same
 * failure, which made the message a hint about which screen you were on rather
 * than about what went wrong.
 */
export const SAVE_ENTRY_ERROR = 'Failed to save entry';

/** Shown when Done is pressed while the account has no category to log into. */
export const NO_CATEGORY_ERROR = 'Pick a category first';

export interface UseEntryDraftOptions {
  /** Categories the draft may target; the first one is the default. */
  categories: Category[];
  /** Entry being edited. Absent (or null) means the draft creates a new entry. */
  entry?: Entry | null;
  /** Category to start in when creating; ignored while editing. */
  categoryId?: number;
  /** Date to start with when creating; defaults to today. */
  date?: string;
  /** Called once, after the entry has been persisted. */
  onSaved: () => void;
}

export interface UseEntryDraftResult {
  categoryId: number;
  /** Switch category; the typed values are dropped along with it. */
  setCategoryId: (categoryId: number) => void;
  entryDate: string;
  setEntryDate: (entryDate: string) => void;
  notes: string;
  setNotes: (notes: string) => void;
  values: EntryDraftValues;
  setValue: (fieldId: number, value: string) => void;
  /** Category the draft currently targets, undefined when there is none. */
  category: Category | undefined;
  /** True while the save request is in flight. */
  saving: boolean;
  /** Text of the last failed save, or null. */
  error: string | null;
  dismissError: () => void;
  /** Persist the draft: create, or update when an entry is being edited. */
  save: () => Promise<void>;
}

/**
 * Draft state plus the save it feeds, so the three entry editors differ only in
 * markup.
 *
 * `entry` is read once, when the hook mounts: the draft is the user's copy and
 * must not be overwritten by a background reload of the list underneath. Give
 * the editor a `key` tied to the entry if it has to be retargeted.
 */
export function useEntryDraft({
  categories,
  entry = null,
  categoryId: initialCategoryId,
  date,
  onSaved,
}: UseEntryDraftOptions): UseEntryDraftResult {
  const [editing] = useState<Entry | null>(entry);
  const [categoryId, setCategoryIdState] = useState<number>(
    editing?.category_id ?? initialCategoryId ?? categories[0]?.id ?? 0
  );
  const [entryDate, setEntryDate] = useState(editing?.entry_date ?? date ?? todayISO());
  const [notes, setNotes] = useState(editing?.notes ?? '');
  const [values, setValues] = useState<EntryDraftValues>(() =>
    editing ? draftValuesFromEntry(editing) : {}
  );
  const [saving, setSaving] = useState(false);
  /** Same fact as `saving`, readable synchronously — see the guard in `save`. */
  const savingRef = useRef(false);
  const [error, setError] = useState<string | null>(null);

  const category = useMemo(
    () => categories.find((candidate) => candidate.id === categoryId),
    [categories, categoryId]
  );

  const setCategoryId = useCallback((next: number) => {
    setCategoryIdState(next);
    // Field ids are category-scoped, so a kept draft would post values against
    // fields the new category does not own.
    setValues({});
  }, []);

  const setValue = useCallback((fieldId: number, value: string) => {
    setValues((prev) => ({ ...prev, [fieldId]: value }));
  }, []);

  const dismissError = useCallback(() => setError(null), []);

  const save = useCallback(async () => {
    if (!category) {
      setError(NO_CATEGORY_ERROR);
      return;
    }
    // `saving` is state, so it still reads false for a second call made in the
    // same tick as the first — two submits then post the same draft twice. The
    // ref updates synchronously, so it is the one that can refuse.
    if (savingRef.current) return;
    savingRef.current = true;
    setSaving(true);
    setError(null);
    const payload = {
      entry_date: entryDate,
      notes: notes || undefined,
      values: toEntryValues(category, values),
    };
    try {
      if (editing) {
        await entriesAPI.update(editing.id, payload);
      } else {
        await entriesAPI.create({ category_id: category.id, ...payload });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : SAVE_ENTRY_ERROR);
      savingRef.current = false;
      setSaving(false);
      return;
    }
    // Released before handing control over: `onSaved` typically unmounts the
    // editor, and a state update after that lands on a component that is gone.
    savingRef.current = false;
    setSaving(false);
    onSaved();
  }, [category, editing, entryDate, notes, onSaved, values]);

  return {
    categoryId,
    setCategoryId,
    entryDate,
    setEntryDate,
    notes,
    setNotes,
    values,
    setValue,
    category,
    saving,
    error,
    dismissError,
    save,
  };
}
