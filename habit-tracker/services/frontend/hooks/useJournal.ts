'use client';
// [review:need-review] PHASE-01/44-mobile-journal, #311
// summary: Journal-screen state extracted from app/journal/page.tsx so the desktop page and /m/journal render the same entries, error and reload behaviour; a successful load retires only the load error, never one the screen reported

// summary: #311 — the list is a key of the shared read cache: a re-visit draws it at once and re-reads it behind the screen (also when the tab comes back)
import { useCallback, useState } from 'react';
import { journalAPI, type JournalEntry } from '@/lib/api';
import { errorMessage, useQuery } from '@/lib/query-cache';

/** How many entries one screenful of the journal asks for. */
const JOURNAL_PAGE_SIZE = 50;

const NO_ENTRIES: JournalEntry[] = [];

const LOAD_JOURNAL_ERROR = 'Failed to load journal';

/** Everything a Journal screen needs; the two shells differ only in markup. */
export interface UseJournalResult {
  entries: JournalEntry[];
  loading: boolean;
  error: string | null;
  setError: (message: string | null) => void;
  /** Re-fetch the list, e.g. after an entry was created, edited or deleted. */
  reload: () => Promise<void>;
}

export function useJournal(): UseJournalResult {
  // Standalone PWA never reloads the document, so returning to /m/journal would
  // otherwise keep rendering the list fetched when the app was launched.
  const { state, refresh } = useQuery(
    'journal',
    () => journalAPI.getAll({ limit: JOURNAL_PAGE_SIZE }).then((page) => page.items),
    { refreshOnVisible: true }
  );
  // What the screen pushed in — a rejected delete, say. It describes something the
  // re-read knows nothing about and survives it; the load's own failure comes
  // from the cache and goes as soon as a read succeeds.
  const [reported, setReported] = useState<string | null>(null);
  // The load failure the reader closed; a later, different failure shows again.
  const [dismissed, setDismissed] = useState<unknown>(null);
  const loadError = state.status === 'loading' ? null : state.error;

  const setError = useCallback(
    (message: string | null) => {
      setReported(message);
      if (message === null) setDismissed(loadError);
    },
    [loadError]
  );

  const reload = useCallback(async () => {
    await refresh();
  }, [refresh]);

  return {
    entries: state.status === 'ready' ? state.data : NO_ENTRIES,
    loading: state.status === 'loading',
    error: reported ?? (loadError === dismissed ? null : errorMessage(state, LOAD_JOURNAL_ERROR)),
    setError,
    reload,
  };
}
