'use client';
// [review:need-review] PHASE-03/93
// summary: goal-screen state for both shells — one fetch of levels, milestones and the current quarter, plus marking a milestone, which re-reads the whole board because closing M9 changes how M10's dependency reads

import { useCallback, useEffect, useState } from 'react';
import { goalsAPI, type GoalsPayload, type MilestoneStatus } from '@/lib/api';

/** Shown when the board cannot be read at all. */
export const LOAD_GOALS_ERROR = 'Не удалось загрузить цели';

/** Everything a goal screen needs; the two shells differ only in markup. */
export interface UseGoalsResult {
  /** The board, or null while loading and after a failure. */
  payload: GoalsPayload | null;
  loading: boolean;
  error: string | null;
  /** Codes whose status is being written right now. */
  saving: Set<string>;
  markMilestone: (code: string, status: MilestoneStatus) => void;
}

/**
 * The goal board: levels, milestones and the goals of the current quarter.
 *
 * `markMilestone` re-reads the whole board rather than patching one milestone
 * into the state it already has. Closing M9 is not a fact about M9 alone —
 * M10 waits on it, and its dependency has to change appearance in the same
 * paint. Patching one row would leave the graph telling the old story.
 */
export function useGoals(): UseGoalsResult {
  const [payload, setPayload] = useState<GoalsPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<Set<string>>(new Set());
  const [refreshCounter, setRefreshCounter] = useState(0);

  useEffect(() => {
    // The screen may unmount while the request is in flight; without this its
    // result would overwrite a newer one.
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const result = await goalsAPI.get();
        if (cancelled) return;
        setPayload(result);
      } catch (err) {
        if (cancelled) return;
        setPayload(null);
        setError(err instanceof Error ? err.message : LOAD_GOALS_ERROR);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [refreshCounter]);

  const markMilestone = useCallback(
    (code: string, status: MilestoneStatus) => {
      setSaving((current) => new Set(current).add(code));
      void (async () => {
        try {
          await goalsAPI.patchMilestone(code, status);
          setRefreshCounter((n) => n + 1);
        } catch (err) {
          setError(err instanceof Error ? err.message : LOAD_GOALS_ERROR);
        } finally {
          setSaving((current) => {
            const next = new Set(current);
            next.delete(code);
            return next;
          });
        }
      })();
    },
    []
  );

  return { payload, loading, error, saving, markMilestone };
}
