'use client';
// [review:need-review] PHASE-03/93, #311
// summary: goal-screen state for both shells — one fetch of levels, milestones and the current quarter, plus marking a milestone, which re-reads the whole board because closing M9 changes how M10's dependency reads
// summary: #311 — the board is a key of the shared read cache: a re-visit draws it at once, and the re-read after a move keeps the board on screen instead of a spinner

import { useCallback, useState } from 'react';
import { goalsAPI, type GoalsPayload, type MilestoneStatus } from '@/lib/api';
import { errorMessage, useQuery } from '@/lib/query-cache';

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
  const { state, refresh } = useQuery('goals', () => goalsAPI.get());
  // A refused move; the board's own load failure comes from the cache.
  const [reported, setReported] = useState<string | null>(null);
  const [saving, setSaving] = useState<Set<string>>(new Set());

  const markMilestone = useCallback(
    (code: string, status: MilestoneStatus) => {
      setSaving((current) => new Set(current).add(code));
      setReported(null);
      void (async () => {
        try {
          await goalsAPI.patchMilestone(code, status);
          await refresh();
        } catch (err) {
          setReported(err instanceof Error ? err.message : LOAD_GOALS_ERROR);
        } finally {
          setSaving((current) => {
            const next = new Set(current);
            next.delete(code);
            return next;
          });
        }
      })();
    },
    [refresh]
  );

  return {
    payload: state.status === 'ready' ? state.data : null,
    loading: state.status === 'loading',
    error: reported ?? (state.status === 'error' ? errorMessage(state, LOAD_GOALS_ERROR) : null),
    saving,
    markMilestone,
  };
}
