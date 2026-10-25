'use client';
// [review:need-review] PHASE-03/209
// summary: loads today's Health catalog once and hands both shells the same discriminated state — shared between /health and /m/health so the two screens cannot answer the same question differently

import { useEffect, useState } from 'react';
import { healthAPI, type HealthMetric } from '@/lib/api';
import { localDate } from '@/lib/health-metrics';

/**
 * State of the one request this screen makes.
 *
 * A discriminated union rather than `{ metrics, loading, error }`: those three
 * booleans-in-disguise can represent "loading and errored at once", a state the
 * single request behind this hook never reaches, and a reader of the page would
 * have to re-derive by hand which combination is actually possible.
 */
export type HealthMetricsState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; metrics: HealthMetric[] };

/** Today's Health catalog, fetched once per mount. */
export function useHealthMetrics(): HealthMetricsState {
  const [state, setState] = useState<HealthMetricsState>({ status: 'loading' });

  useEffect(() => {
    let cancelled = false;
    const today = localDate();
    void healthAPI
      .getMetrics(today, today)
      .then((response) => {
        if (!cancelled) setState({ status: 'ready', metrics: response.metrics });
      })
      .catch(() => {
        if (!cancelled) {
          setState({ status: 'error', message: 'Не удалось загрузить данные здоровья' });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}
