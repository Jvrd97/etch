'use client';
// [review:need-review] PHASE-03/147, PHASE-03/148
// summary: state of building a day's plan from the screen — the model first and the canon-only skeleton as the fallback offered once the model refuses, the wait and the refusal kept as states of one union rather than as two booleans, and a second click ignored while a plan is already being written

import { useCallback, useEffect, useRef, useState } from 'react';
import { dayAPI, type Plan } from '@/lib/api';

/** Said when the failure arrived without a sentence of its own. */
export const BUILD_PLAN_ERROR = 'Не удалось собрать план';

/**
 * Where the building of a plan currently is.
 *
 * A union rather than `loading`/`error` flags, because the two ways of building
 * are not interchangeable: «модель думает» and «собираю скелет» wait for
 * different things and are worth different amounts of patience, and a reader
 * who cannot tell them apart cannot tell a slow model from a stuck screen.
 */
export type PlanBuildState =
  | { status: 'idle' }
  | { status: 'generating' }
  | { status: 'skeleton' }
  | { status: 'failed'; message: string };

export interface UsePlanBuildResult {
  state: PlanBuildState;
  /** Ask the model. The server falls back to the skeleton on its own. */
  generate: () => Promise<void>;
  /** Build the day out of the canon, without the model. */
  buildSkeleton: () => Promise<void>;
}

/**
 * The two ways out of a day with no plan.
 *
 * Generation is the main path: the server answers it with a plan whatever the
 * model does, and only a request that never got an answer — no network, a date
 * outside the canon, a refusal on write — lands here as a failure. The skeleton
 * is therefore offered as a fallback and not as a twin button: a second button
 * of equal weight would be the one chosen every morning, and the day would
 * quietly stop being planned by anything but the canon.
 *
 * `onBuilt` re-reads the day rather than patching it in: the server has just
 * numbered the sections, measured the schedule and recorded which rules the new
 * plan broke, and none of that can be guessed on the screen.
 */
export function usePlanBuild(date: string, onBuilt: () => void): UsePlanBuildResult {
  const [state, setState] = useState<PlanBuildState>({ status: 'idle' });
  // The card unmounts the moment the plan arrives, and the answer of a request
  // that outlived it must not be written into a component that is gone.
  const alive = useRef(true);
  // A ref rather than the state above: two clicks land in the same React batch,
  // and a second POST would write a second plan over the first.
  const busy = useRef(false);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const run = useCallback(
    async (running: 'generating' | 'skeleton', build: () => Promise<Plan>) => {
      if (busy.current) return;
      busy.current = true;
      setState({ status: running });
      try {
        await build();
        if (!alive.current) return;
        setState({ status: 'idle' });
        onBuilt();
      } catch (err) {
        if (!alive.current) return;
        setState({
          status: 'failed',
          message: err instanceof Error ? err.message : BUILD_PLAN_ERROR,
        });
      } finally {
        busy.current = false;
      }
    },
    [onBuilt]
  );

  const generate = useCallback(
    () => run('generating', () => dayAPI.generatePlan(date)),
    [date, run]
  );

  const buildSkeleton = useCallback(
    () => run('skeleton', () => dayAPI.buildSkeleton(date)),
    [date, run]
  );

  return { state, generate, buildSkeleton };
}
