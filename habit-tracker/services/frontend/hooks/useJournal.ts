'use client';
// [review:need-review] PHASE-01/44-mobile-journal
// summary: Journal-screen state extracted from app/journal/page.tsx so the desktop page and /m/journal render the same entries, error and reload behaviour; a successful load retires only the load error, never one the screen reported

import { useCallback, useEffect, useState } from 'react';
import { useRefreshOnVisible } from '@/hooks/useRefreshOnVisible';
import { journalAPI, type JournalEntry } from '@/lib/api';

/** How many entries one screenful of the journal asks for. */
const JOURNAL_PAGE_SIZE = 50;

/**
 * The banner message plus where it came from.
 *
 * The origin matters because a successful load may only retire a *load*
 * failure. A message the screen pushed in — a rejected delete, say — describes
 * something the refetch knows nothing about and has to survive it.
 */
interface JournalError {
  message: string;
  fromLoad: boolean;
}

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
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [errorState, setErrorState] = useState<JournalError | null>(null);

  const setError = useCallback((message: string | null) => {
    setErrorState(message === null ? null : { message, fromLoad: false });
  }, []);

  /**
   * Fetch the list.
   *
   * `showSpinner` separates the first load — nothing on screen yet, so a spinner
   * is the honest state — from a reload after a mutation or a silent refresh,
   * where the previous list stays rendered until the new one lands. Flipping
   * `loading` there would blank a screen the user is looking at.
   */
  const loadData = useCallback(async ({ showSpinner = false } = {}) => {
    try {
      if (showSpinner) setLoading(true);
      const data = await journalAPI.getAll({ limit: JOURNAL_PAGE_SIZE });
      setEntries(data.items);
      // A reload that succeeds must retire the previous *load* failure, or the
      // error banner outlives the outage that caused it. Anything the screen
      // reported stays: the silent refresh on `visibilitychange` fires exactly
      // when the user comes back to read it.
      setErrorState((previous) => (previous?.fromLoad ? null : previous));
    } catch (err) {
      setErrorState({
        message: err instanceof Error ? err.message : 'Failed to load journal',
        fromLoad: true,
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData({ showSpinner: true });
  }, [loadData]);

  const reload = useCallback(async () => {
    await loadData();
  }, [loadData]);

  const refresh = useCallback(() => {
    void loadData();
  }, [loadData]);

  // Standalone PWA never reloads the document, so returning to /m/journal would
  // otherwise keep rendering the list fetched when the app was launched.
  useRefreshOnVisible(refresh);

  return {
    entries,
    loading,
    error: errorState?.message ?? null,
    setError,
    reload,
  };
}
