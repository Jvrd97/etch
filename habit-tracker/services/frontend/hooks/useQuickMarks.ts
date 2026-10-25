'use client';
// [review:need-review] PHASE-03/121, PHASE-03/124, PHASE-03/130, PHASE-01/206
// summary: the quick-mark directory as Today reads it — one fetch, the order and the `planned` flag taken from the server rather than recomputed, a tap that repaints from its own answer instead of asking the directory again, and a word to the screen after every tap or undo that went through saying which category's day moved, so the records and streaks beside the buttons can be read again

import { useCallback, useEffect, useState } from 'react';
import { quickMarksAPI, type QuickMark, type QuickMarkEvent } from '@/lib/api';
import { applyQuickMarkEvent, applyQuickMarkUndo } from '@/lib/quick-marks';

/** What the reader sees when a tap did not reach the server. */
export const TAP_FAILED = 'Отметку записать не удалось.';

/** What the reader sees when taking the tap back did not reach the server. */
export const UNDO_FAILED = 'Отменить отметку не удалось.';

export interface UseQuickMarksOptions {
  /**
   * A tap or an undo went through: the day of this category moved.
   *
   * The buttons repaint from the answer on their own, but the records and the
   * streaks of the same screen are somebody else's state, and a screen that is
   * not told keeps showing the day as it was before the tap. Only a call that
   * reached the server says it — a refusal changed nothing to re-read.
   */
  onDayChanged?: (categoryId: number) => void;
}

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
  /**
   * Take back one named tap — the row of the day's list, not necessarily the
   * last tap of the session.
   *
   * Resolves with the server's sentence when it refuses, and null once the tap
   * is gone. The sentence is the caller's to show where the reader is looking:
   * the list that asked for the undo is on top of the screen, and an error
   * parked in this hook's `error` would sit under it.
   */
  undoEvent: (eventId: number) => Promise<string | null>;
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
export function useQuickMarks({ onDayChanged }: UseQuickMarksOptions = {}): UseQuickMarksResult {
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

  const tap = useCallback(
    async (id: number) => {
      setError(null);
      let event: QuickMarkEvent;
      try {
        event = await quickMarksAPI.tap(id);
      } catch (err) {
        setError(err instanceof Error ? err.message : TAP_FAILED);
        return;
      }
      setMarks((current) => applyQuickMarkEvent(current, event));
      setLastEvent(event);
      const mark = marks.find((candidate) => candidate.id === id);
      if (mark) onDayChanged?.(mark.category_id);
    },
    [marks, onDayChanged]
  );

  const takeBack = useCallback(
    async (eventId: number): Promise<string | null> => {
      try {
        const undone = await quickMarksAPI.undo(eventId);
        setMarks((current) => applyQuickMarkUndo(current, undone));
        const mark = marks.find((candidate) => candidate.id === undone.quick_mark_id);
        if (mark) onDayChanged?.(mark.category_id);
        return null;
      } catch (err) {
        return err instanceof Error ? err.message : UNDO_FAILED;
      } finally {
        // The offer to undo is spent for the tap that was just dealt with, in
        // both outcomes: a success took it back, and a refusal means it is no
        // longer the last one — a button answering 409 forever is worse than
        // none. A different tap keeps its offer.
        setLastEvent((current) => (current?.event_id === eventId ? null : current));
      }
    },
    [marks, onDayChanged]
  );

  const undo = useCallback(async () => {
    if (lastEvent === null) return;
    const refusal = await takeBack(lastEvent.event_id);
    if (refusal !== null) setError(refusal);
  }, [lastEvent, takeBack]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);

  return { marks, loading, error, tap, lastEvent, undo, undoEvent: takeBack, reload };
}
