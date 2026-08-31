'use client';
// [review:need-review] PHASE-03/138
// summary: one read of the role summary over a period — the week page and /roles use the same hook, because the fold is one endpoint and a second reader of it would be a second answer

import { useEffect, useState } from 'react';
import { rolesAPI, type RoleSummary } from '@/lib/api';

/** Что читает экран, показывающий сводку ролей. */
export interface UseRoleSummaryResult {
  summary: RoleSummary | null;
  loading: boolean;
  error: string | null;
}

/**
 * Сводка ролей за период.
 *
 * Период приходит параметром, а не считается здесь: неделя знает свои границы
 * из строки недели, `/roles` — из выбора человека, и вычислять их второй раз
 * значило бы завести второе представление о том, что такое «эта неделя».
 *
 * `null` в любой из границ — «период ещё не известен»: страница недели узнаёт
 * его после своего запроса, и до тех пор спрашивать сводку не о чем.
 */
export function useRoleSummary(
  dateFrom: string | null,
  dateTo: string | null
): UseRoleSummaryResult {
  const [summary, setSummary] = useState<RoleSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (dateFrom === null || dateTo === null) return;
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const answer = await rolesAPI.summary(dateFrom, dateTo);
        if (!cancelled) {
          setSummary(answer);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Сводка не прочиталась');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [dateFrom, dateTo]);

  return { summary, loading, error };
}
