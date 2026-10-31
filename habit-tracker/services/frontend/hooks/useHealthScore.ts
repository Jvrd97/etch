'use client';
// [review:need-review] PHASE-03/303
// summary: reads the health index of the day from GET /dashboard/summary once on mount; a missing endpoint or a failed read leaves the «Состояние сегодня» card out (null), as the sleep section does, because the index is computed on the server and never guessed on the client

import { useEffect, useState } from 'react';
// A namespace import read at call time: suites that mock `@/lib/api` with a
// fixed list of names keep linking every screen that renders Health.
import * as api from '@/lib/api';
import type { HealthScore, HealthScoreResponse } from '@/lib/api';

export type HealthScoreRead = () => Promise<HealthScoreResponse>;

const API_READ: HealthScoreRead = () => api.healthScoreAPI.today();

/** The server's index; null before the answer and after a failed read. */
export function useHealthScore(read: HealthScoreRead = API_READ): HealthScore | null {
  const [score, setScore] = useState<HealthScore | null>(null);

  useEffect(() => {
    let alive = true;
    // `Promise.resolve().then` also turns a synchronous throw from `read` into a rejection.
    Promise.resolve()
      .then(read)
      .then((body) => {
        if (alive) setScore(body.scores.health);
      })
      .catch((error: unknown) => {
        console.warn('индекс здоровья не прочитался, карточку не показываем', error);
      });
    return () => {
      alive = false;
    };
  }, [read]);

  return score;
}
