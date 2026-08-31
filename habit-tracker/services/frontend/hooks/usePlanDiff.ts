'use client';
// [review:need-review] PHASE-03/150
// summary: один запрос дифа плана дня — что предлагала машина против того, что стоит; ошибка чтения дифа гасится, а не ломает экран дня, потому что диф это подпись, а не сам план

import { useEffect, useState } from 'react';
import { dayAPI, type PlanDiff } from '@/lib/api';

export interface UsePlanDiffResult {
  diff: PlanDiff | null;
}

/**
 * Диф плана на дату, или `null`, пока его нет.
 *
 * Ошибка чтения не поднимается наверх и не рисует полосу: диф — подпись под
 * пунктом, и день без неё остаётся днём. Полоса «не удалось загрузить диф» над
 * рабочим планом — ровно тот шум, который учат не замечать.
 *
 * `revalidateOn` — что угодно, чья смена значит «план изменился»: экран дня
 * передаёт сюда план, который вернул сервер после последней правки. План и диф
 * меняются одним действием, и второй обязан перечитаться вместе с первым.
 */
export function usePlanDiff(date: string, revalidateOn?: unknown): UsePlanDiffResult {
  const [diff, setDiff] = useState<PlanDiff | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const loaded = await dayAPI.getPlanDiff(date);
        if (!cancelled) setDiff(loaded);
      } catch {
        // Подпись, которой не будет, — не поломка дня.
        if (!cancelled) setDiff(null);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [date, revalidateOn]);

  return { diff };
}
