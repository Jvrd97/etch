'use client';
// [review:need-review] PHASE-03/88
// summary: mark state for both day shells — a click walks the ring and is sent as an explicit state, the screen updates before the round trip and rolls back if the server refuses, and the task counter is recomputed locally so the header moves with the click

import { useCallback, useEffect, useMemo, useState } from 'react';
import { dayAPI, type Mark, type MarkState, type TaskCounts } from '@/lib/api';
import { marksByItem, nextMarkState } from '@/lib/marks';

/** Said when the server refused a mark; the click is rolled back under it. */
export const SAVE_MARK_ERROR = 'Отметка не сохранилась';

export interface UseDayMarksResult {
  /** Every mark of the day, by item id. */
  marks: Map<string, Mark>;
  /** Tasks by what happened to them, recomputed after every click. */
  counts: TaskCounts;
  /** Item ids with a write in flight, so a line can say it is saving. */
  saving: Set<string>;
  error: string | null;
  /** One click: пусто → done → failed → пусто. */
  cycle: (itemId: string) => void;
  /** Set a state directly — `skipped` is only reachable this way. */
  setState: (itemId: string, state: MarkState | null) => void;
  /** Write the "как прошло" note without touching the state. */
  setNote: (itemId: string, note: string) => void;
}

/**
 * The marks of one day.
 *
 * The click is applied locally first and sent as an explicit target state.
 * Sending "the next one" would make two open tabs disagree about what a click
 * means; sending the state makes the same request twice a no-op and the last
 * writer the winner, which is what the server is built to do.
 *
 * Counting happens here rather than on the server's answer, because the header
 * has to move with the click rather than a round trip later. The server's own
 * count arrives with the next read of the day and settles any disagreement.
 */
export function useDayMarks(
  date: string,
  initial: Mark[],
  kinds: Map<string, string>
): UseDayMarksResult {
  const [marks, setMarks] = useState<Map<string, Mark>>(() =>
    marksByItem(initial)
  );
  const [saving, setSaving] = useState<Set<string>>(() => new Set());
  const [error, setError] = useState<string | null>(null);

  // What the server last said, as one string. The effect below keys off this
  // rather than off the array: a caller that rebuilds `initial` on every render
  // — which is the normal shape of `detail?.marks ?? []` — would otherwise put
  // the screen in a render loop, and a hook that only works when its caller
  // remembers to memoise is a trap rather than a hook.
  const signature = useMemo(
    () =>
      initial
        .map(
          (m) =>
            `${m.item_id}:${m.state ?? ''}:${m.note ?? ''}:${m.updated_at ?? ''}`
        )
        .join('|'),
    [initial]
  );

  // The day was re-read (another date, a reload): the server's marks replace
  // whatever this hook was holding, including a failed optimistic write.
  useEffect(() => {
    setMarks(marksByItem(initial));
    setError(null);
    // `initial` is deliberately not a dependency; `signature` is its content.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [date, signature]);

  const counts = useMemo<TaskCounts>(() => {
    let planned = 0;
    let done = 0;
    let failed = 0;
    let skipped = 0;
    kinds.forEach((kind, itemId) => {
      if (kind !== 'task') return;
      planned += 1;
      const state = marks.get(itemId)?.state ?? null;
      if (state === 'done') done += 1;
      else if (state === 'failed') failed += 1;
      else if (state === 'skipped') skipped += 1;
    });
    return {
      planned,
      done,
      failed,
      skipped,
      pending: planned - done - failed - skipped,
    };
  }, [kinds, marks]);

  const write = useCallback(
    async (itemId: string, state: MarkState | null, note: string | null) => {
      const previous = marks.get(itemId) ?? null;

      setMarks((current) => {
        const next = new Map(current);
        if (state === null) next.delete(itemId);
        else {
          next.set(itemId, {
            item_id: itemId,
            state,
            note,
            marked_at: previous?.marked_at ?? null,
            updated_at: previous?.updated_at ?? null,
            source: 'web',
          });
        }
        return next;
      });
      setSaving((current) => new Set(current).add(itemId));
      setError(null);

      try {
        const stored = await dayAPI.setMark(date, itemId, { state, note });
        setMarks((current) => {
          const next = new Map(current);
          if (stored.state === null) next.delete(itemId);
          else next.set(itemId, stored);
          return next;
        });
      } catch (err) {
        // Rolled back rather than left hanging: a tick that stayed on screen
        // after the write failed is exactly the lie the file-backed page told.
        setMarks((current) => {
          const next = new Map(current);
          if (previous === null) next.delete(itemId);
          else next.set(itemId, previous);
          return next;
        });
        setError(err instanceof Error ? err.message : SAVE_MARK_ERROR);
      } finally {
        setSaving((current) => {
          const next = new Set(current);
          next.delete(itemId);
          return next;
        });
      }
    },
    [date, marks]
  );

  const setState = useCallback(
    (itemId: string, state: MarkState | null) => {
      void write(itemId, state, marks.get(itemId)?.note ?? null);
    },
    [marks, write]
  );

  const cycle = useCallback(
    (itemId: string) => {
      const current = marks.get(itemId)?.state ?? null;
      void write(itemId, nextMarkState(current), marks.get(itemId)?.note ?? null);
    },
    [marks, write]
  );

  const setNote = useCallback(
    (itemId: string, note: string) => {
      const state = marks.get(itemId)?.state ?? null;
      // The note lives on the mark row, so a line with no mark has nowhere to
      // put it. The screen offers the field only where there is a mark, and
      // this guards the same rule for anything that calls the hook directly.
      if (state === null) return;
      void write(itemId, state, note === '' ? null : note);
    },
    [marks, write]
  );

  return { marks, counts, saving, error, cycle, setState, setNote };
}
