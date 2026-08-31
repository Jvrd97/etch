'use client';
// [review:need-review] PHASE-03/92
// summary: the derived training state for both shells — one fetch of the snapshot, its gated suggestion and the open complaints, with a failure left as null rather than thrown at the day screen

import { useCallback, useEffect, useState } from 'react';
import { trainingAPI, type TrainingState } from '@/lib/api';

export interface UseTrainingStateResult {
  state: TrainingState | null;
  loading: boolean;
  reload: () => void;
}

/**
 * The state of the body: dates of the last patterns, week volume, skips.
 *
 * A failure comes back as `null` rather than as an error banner. The training
 * block sits inside the day screen, and a day that loaded fine must not be
 * replaced by a message about training — the block simply says nothing about a
 * state it could not read.
 */
export function useTrainingState(enabled = true): UseTrainingStateResult {
  const [state, setState] = useState<TrainingState | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [counter, setCounter] = useState(0);

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      try {
        const result = await trainingAPI.getState();
        if (!cancelled) setState(result);
      } catch {
        // Deliberately swallowed and made visible as an absent block: see above.
        if (!cancelled) setState(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [enabled, counter]);

  const reload = useCallback(() => setCounter((n) => n + 1), []);

  return { state, loading, reload };
}
