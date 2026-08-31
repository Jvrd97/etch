'use client';
// [review:need-review] PHASE-03/121, PHASE-03/124, PHASE-03/130
// summary: the quick-mark directory as Today reads it — one fetch, the order and the `planned` flag taken from the server rather than recomputed, and a tap that repaints from its own answer instead of asking the directory again

import { useCallback, useEffect, useState } from 'react';
import { quickMarksAPI, type QuickMark, type QuickMarkEvent } from '@/lib/api';
import { applyQuickMarkEvent, applyQuickMarkUndo } from '@/lib/quick-marks';

/** What the reader sees when a tap did not reach the server. */
export const TAP_FAILED = 'Отметку записать не удалось.';

/** What the reader sees when taking the tap back did not reach the server. */
export const UNDO_FAILED = 'Отменить отметку не удалось.';

export interface UseQuickMarksResult {
  /** The directory in the order the server decided: planned buttons first. */
  marks: QuickMark[];
  loading: boolean;
  error: string | null;
  /** Record one tap; the list repaints from the tap's own answer. */
  tap: (id: number) => Promise<void>;
  /** The tap that can still be taken back, or null when none can. */
  lastEvent: QuickMarkEvent | null;
  /**
   * Take the last tap back — one action, no trip to the entry editor (`#124`).
   *
   * A refusal (the value was edited by hand, the tap is no longer the last one)
   * comes back as the server's sentence in `error` and retires the affordance:
   * the tap it pointed at is not undoable any more, and offering it again would
   * be a button that answers 409 forever.
   */
  undo: () => Promise<void>;
  /** Forget the error and re-read the directory. */
  reload: () => void;
}

/**
 * The quick-mark buttons of Today.
 *
 * Neither the order nor the `planned` flag is computed here. Both come from
 * `GET /quick-marks`, because the same selection serves the web, the floating
 * window of the agent and iOS — and an order computed in the browser would be
 * an order the other two do not have.
 *
 * A tap costs one call. `POST .../events` answers with the new `today_total`
 * and `done`, so the row repaints from the response; asking the directory again
 * would double the traffic of the one gesture this screen exists for.
 */
export function useQuickMarks(): UseQuickMarksResult {
  const [marks, setMarks] = useState<QuickMark[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [lastEvent, setLastEvent] = useState<QuickMarkEvent | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const directory = await quickMarksAPI.list();
        if (!cancelled) setMarks(directory);
      } catch (err) {
        // Пустой справочник и недоступный справочник — разные вещи, но обе
        // означают «кнопок на экране нет». Ошибка показывается, список не
        // выдумывается.
        if (!cancelled) setError(err instanceof Error ? err.message : TAP_FAILED);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const tap = useCallback(async (id: number) => {
    setError(null);
    try {
      const event = await quickMarksAPI.tap(id);
      setMarks((current) => applyQuickMarkEvent(current, event));
      setLastEvent(event);
    } catch (err) {
      setError(err instanceof Error ? err.message : TAP_FAILED);
    }
  }, []);

  const undo = useCallback(async () => {
    if (lastEvent === null) return;
    try {
      const undone = await quickMarksAPI.undo(lastEvent.event_id);
      setMarks((current) => applyQuickMarkUndo(current, undone));
    } catch (err) {
      setError(err instanceof Error ? err.message : UNDO_FAILED);
    } finally {
      // Отменять нечего в обоих исходах: удачный снял тап, отказ означает, что
      // этот тап уже не последний, и кнопка, отвечающая 409 навсегда, — хуже её
      // отсутствия.
      setLastEvent(null);
    }
  }, [lastEvent]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);

  return { marks, loading, error, tap, lastEvent, undo, reload };
}
