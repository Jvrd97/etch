'use client';
// [review:need-review] PHASE-03/127, PHASE-03/128, PHASE-03/129
// summary: challenge state for both shells — one list request (which is also what materializes the missed days), creation, counting a day by hand, accepting or declining a proposal the model made, and a refetch after any write, because a challenge's counts and its status are the server's arithmetic and never the browser's

import { useCallback, useEffect, useState } from 'react';
import { challengesAPI, type Challenge, type ChallengeDraft } from '@/lib/api';

/** Shown when the list cannot be read at all. */
export const LOAD_CHALLENGES_ERROR = 'Не удалось загрузить челленджи';

/** Shown when the hand-written verdict could not be saved. */
export const COUNT_DAY_ERROR = 'Не удалось засчитать день';

/** Shown when the answer to a proposal did not reach the server. */
export const ANSWER_PROPOSAL_ERROR = 'Не удалось ответить на предложение';

export interface UseChallengesResult {
  challenges: Challenge[];
  loading: boolean;
  error: string | null;
  /** Create an obligation and re-read the list it lands in. */
  create: (draft: ChallengeDraft) => Promise<void>;
  /** Count one day by hand; the server recomputes the status from it. */
  countToday: (id: number, day: string) => Promise<void>;
  /** Ids whose manual verdict is being written right now. */
  counting: Set<number>;
  /** Take on a proposal: it becomes an obligation and starts counting. */
  accept: (id: number) => Promise<void>;
  /** Turn a proposal down; it is abandoned and does not come back. */
  decline: (id: number) => Promise<void>;
  /** Ids whose answer to a proposal is in flight. */
  answering: Set<number>;
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
  const [counting, setCounting] = useState<Set<number>>(new Set());
  const [answering, setAnswering] = useState<Set<number>>(new Set());

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

  const countToday = useCallback(
    async (id: number, day: string) => {
      setCounting((current) => new Set(current).add(id));
      try {
        await challengesAPI.setDayVerdict(id, day, { verdict: 'done' });
        reload();
      } catch (err) {
        setError(err instanceof Error ? err.message : COUNT_DAY_ERROR);
      } finally {
        setCounting((current) => {
          const next = new Set(current);
          next.delete(id);
          return next;
        });
      }
    },
    [reload],
  );

  /**
   * Ответ на предложение — «принять» или «отклонить» — и перечитанный список.
   *
   * Оба ответа ходят одним путём: разница между ними ровно в вызове, а не в
   * том, что происходит с экраном. Принятое предложение приезжает обратно
   * посчитанным (принятие материализует окно), отклонённое — брошенным, и
   * собирать это в браузере значило бы завести вторую арифметику.
   */
  const answer = useCallback(
    async (id: number, call: (id: number) => Promise<unknown>) => {
      setAnswering((current) => new Set(current).add(id));
      try {
        await call(id);
        reload();
      } catch (err) {
        setError(err instanceof Error ? err.message : ANSWER_PROPOSAL_ERROR);
      } finally {
        setAnswering((current) => {
          const next = new Set(current);
          next.delete(id);
          return next;
        });
      }
    },
    [reload],
  );

  const accept = useCallback(
    (id: number) => answer(id, challengesAPI.accept),
    [answer],
  );

  const decline = useCallback(
    (id: number) => answer(id, challengesAPI.decline),
    [answer],
  );

  return {
    challenges,
    loading,
    error,
    create,
    countToday,
    counting,
    accept,
    decline,
    answering,
    reload,
  };
}
