'use client';
// [review:need-review] PHASE-03/92
// summary: anchor state for both day shells — a click ticks the anchor and moves the counter locally, the write names the kind and is settled by the server's answer, a refusal is rolled back and re-thrown, and a re-read day replaces whatever the hook was holding

import { useCallback, useMemo, useState } from 'react';
import type { AnchorState, DayAnchor, DayAnchors } from '@/lib/api';
import { dayAPI } from '@/lib/api';

/**
 * The states under which an anchor does not lower the day.
 *
 * `skipped` closes an anchor exactly as `done` does — an anchor that stopped
 * being relevant is not one the day missed. This is `CLOSING_ANCHOR_STATES` of
 * `app/models/anchor.py`, named here because the screen has to count the same
 * way the verdict beside it counts.
 */
const CLOSING: ReadonlySet<AnchorState> = new Set<AnchorState>(['done', 'skipped']);

export interface UseDayAnchorsResult {
  /** The anchors of the day as the screen should draw them right now. */
  payload: DayAnchors;
  /**
   * Write one anchor. Resolves once the server has stored it; rejects — after
   * rolling the click back — when it refused, so the row can say so.
   */
  mark: (kind: string, state: AnchorState | null) => Promise<void>;
}

/** Recount `done` and `missing` the way `app/api/day.py` counts them. */
function recount(anchors: DayAnchor[], total: number): DayAnchors {
  const required = anchors.filter((a) => a.required_today);
  const closed = (a: DayAnchor) => a.state !== null && CLOSING.has(a.state);
  return {
    day_date: '',
    anchors,
    total,
    done: required.filter(closed).length,
    missing: required.filter((a) => !closed(a)).map((a) => a.title),
  };
}

/**
 * The anchors of one day, ticked before the round trip.
 *
 * The click used to travel to the server and come back as a re-read of the
 * whole day: the box stayed empty until it did, and then the screen was
 * replaced by a spinner and rebuilt — one tick read as the page reloading
 * itself. Here the tick is applied locally, the write names the kind, and the
 * server's answer — which is the whole block, recounted — replaces the guess.
 *
 * The counter and «Не закрыты» are recomputed locally on the same rule the
 * server uses, because a header that moved a round trip after the box would be
 * the same lag in a smaller place. Nothing here is a second source of truth:
 * every write ends with the server's own numbers, and so does every re-read of
 * the day.
 */
export function useDayAnchors(date: string, initial: DayAnchors): UseDayAnchorsResult {
  const [payload, setPayload] = useState<DayAnchors>(initial);

  // What the server last said, as one string. The screen passes
  // `detail.anchors` — a fresh object on every render — so keying off the
  // reference would reset the hook forever; keying off the content resets it
  // exactly when the day was actually re-read.
  const signature = useMemo(
    () =>
      `${initial.day_date}|${initial.done}/${initial.total}|` +
      initial.anchors
        .map((a) => `${a.kind}:${a.state ?? ''}:${a.required_today ? 1 : 0}`)
        .join(','),
    [initial]
  );
  const [shown, setShown] = useState(signature);

  // Adjusted during the render rather than in an effect: an effect would draw
  // the stale block once and correct it on the next frame, and the day screen
  // re-reads after every write — that frame is exactly the flash this hook
  // exists to remove. React re-runs the render immediately instead.
  if (shown !== signature) {
    setShown(signature);
    setPayload(initial);
  }

  const mark = useCallback(
    async (kind: string, state: AnchorState | null) => {
      const before = payload;
      const guess = recount(
        before.anchors.map((a) => (a.kind === kind ? { ...a, state } : a)),
        before.total
      );
      setPayload({ ...guess, day_date: before.day_date });

      try {
        // The kind, not the position: the order of the list is a property of
        // the screen, and a write that leaned on it would break the first time
        // a kind is added to the catalogue.
        setPayload(await dayAPI.setAnchors(date, [{ kind, state }]));
      } catch (err) {
        // Rolled back rather than left standing: a tick that survived a failed
        // write is a screen lying about what the day holds.
        setPayload(before);
        throw err;
      }
    },
    [date, payload]
  );

  return { payload, mark };
}
