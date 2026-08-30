'use client';
// [review:need-review] PHASE-03/127
// summary: challenge state for both shells — one list request (which is also what materializes the missed days), creation, and a refetch after any write, because a challenge's counts are the server's arithmetic and never the browser's

import { useCallback, useEffect, useState } from 'react';
import { challengesAPI, type Challenge, type ChallengeDraft } from '@/lib/api';

/** Shown when the list cannot be read at all. */
export const LOAD_CHALLENGES_ERROR = 'Не удалось загрузить челленджи';

export interface UseChallengesResult {
  challenges: Challenge[];
  loading: boolean;
  error: string | null;
  /** Create an obligation and re-read the list it lands in. */
  create: (draft: ChallengeDraft) => Promise<void>;
  reload: () => void;
}

/**
 * Обязательства текущего человека.
 *
 * После любой записи список перечитывается целиком, а не патчится в состоянии.
 * Причина не в лени: чтение — это и есть материализация. Ответ сервера несёт
 * досчитанные вердикты и пересчитанный счёт, а собранная в браузере копия
 * показывала бы вчерашние числа с сегодняшней датой.
 */
export function useChallenges(): UseChallengesResult {
  const [challenges, setChallenges] = useState<Challenge[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshCounter, setRefreshCounter] = useState(0);

  const reload = useCallback(() => {
    setRefreshCounter((counter) => counter + 1);
  }, []);

  useEffect(() => {
    // The screen may unmount while the request is in flight; without this its
    // result would overwrite a newer one.
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const result = await challengesAPI.list();
        if (cancelled) return;
        setChallenges(result);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : LOAD_CHALLENGES_ERROR);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [refreshCounter]);

  const create = useCallback(
    async (draft: ChallengeDraft) => {
      await challengesAPI.create(draft);
      reload();
    },
    [reload],
  );

  return { challenges, loading, error, create, reload };
}
