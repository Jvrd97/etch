'use client';
// [review:need-review] PHASE-03/152
// summary: state of the rules screen — one read of every version of the canon plus the earliest date a new one may start on, and a publish that re-reads the history instead of patching it, because publishing also closes the version that was in force

import { useCallback, useEffect, useState } from 'react';
import { dayRulesAPI, type DayRuleSetHistory, type DayRuleSetPublish } from '@/lib/api';

/** Shown when the versions cannot be read at all. */
export const LOAD_RULES_ERROR = 'Не удалось загрузить правила дня';

/** Shown when a publication failed without the server saying why. */
export const PUBLISH_RULES_ERROR = 'Не удалось выпустить новую версию';

/** Everything the rules screen needs; the markup is the component's business. */
export interface UseDayRulesResult {
  /** Every version and the dates around publishing; null while loading and after a failure. */
  history: DayRuleSetHistory | null;
  loading: boolean;
  error: string | null;
  publishing: boolean;
  /** Why the last publication was refused — the server's sentence, verbatim. */
  publishError: string | null;
  /** `valid_from` of the version published last, so the screen can confirm it. */
  publishedFrom: string | null;
  publish: (payload: DayRuleSetPublish) => Promise<boolean>;
}

/**
 * The history of the canon, and the one write there is.
 *
 * `publish` re-reads the whole history rather than appending the new version to
 * the state it already has. Publishing is two writes — the version in force is
 * closed at the new date, the new one is inserted — so a screen that appended
 * would show the previous version still open-ended, that is, two versions in
 * force at once, which is exactly what the table forbids.
 *
 * The refusal text is kept as the server wrote it. The two things that can go
 * wrong — «дата уже прожита» and «период перекрывает записанный» — are
 * different acts to repair, and a single «не получилось» would hide which.
 */
export function useDayRules(): UseDayRulesResult {
  const [history, setHistory] = useState<DayRuleSetHistory | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [publishing, setPublishing] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);
  const [publishedFrom, setPublishedFrom] = useState<string | null>(null);
  const [refreshCounter, setRefreshCounter] = useState(0);

  useEffect(() => {
    // The screen may unmount while the request is in flight; without this its
    // result would overwrite a newer one.
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const result = await dayRulesAPI.getHistory();
        if (cancelled) return;
        setHistory(result);
      } catch (err) {
        if (cancelled) return;
        setHistory(null);
        setError(err instanceof Error ? err.message : LOAD_RULES_ERROR);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [refreshCounter]);

  const publish = useCallback(async (payload: DayRuleSetPublish): Promise<boolean> => {
    setPublishing(true);
    setPublishError(null);
    try {
      await dayRulesAPI.publish(payload);
      setPublishedFrom(payload.valid_from);
      setRefreshCounter((n) => n + 1);
      return true;
    } catch (err) {
      setPublishError(err instanceof Error ? err.message : PUBLISH_RULES_ERROR);
      return false;
    } finally {
      setPublishing(false);
    }
  }, []);

  return { history, loading, error, publishing, publishError, publishedFrom, publish };
}
