'use client';
// [review:need-review] PHASE-03/121, PHASE-03/124, PHASE-03/130, PHASE-01/206, #311
// summary: the quick-mark directory as Today reads it — one fetch, the order and the `planned` flag taken from the server rather than recomputed, a tap that repaints from its own answer instead of asking the directory again, and a word to the screen after every tap or undo that went through saying which category's day moved, so the records and streaks beside the buttons can be read again

// summary: #311 — the directory lives in the shared read cache (Today's snapshot reads the same key, so the page has one copy and a re-visit draws the buttons at once); a tap is drawn before the server answers, goes out under an `Idempotency-Key` (one button's taps one after another) and is retried once under the same key, a tap that fails is withdrawn alone, and once a button has no tap in flight it takes the newest answer the server gave
import { useCallback, useState } from 'react';
// A namespace import read at call time, as in `useDayMode`: suites that mock
// `@/lib/api` with a fixed list of names must still link every screen of Today.
import * as api from '@/lib/api';
import type { QuickMark, QuickMarkEvent } from '@/lib/api';
import {
  dataOr,
  errorMessage,
  fetchQuery,
  getQueryData,
  setQueryData,
  useQuery,
  useQueryData,
} from '@/lib/query-cache';
import {
  applyQuickMarkEvent,
  applyQuickMarkTap,
  applyQuickMarkUndo,
  newTapKey,
} from '@/lib/quick-marks';

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
  /** Forget the error: the reader has seen which tap was taken off. */
  clearError: () => void;
}

/** The cache key of the directory Today draws its buttons from. */
export const QUICK_MARKS_KEY = 'quickMarks';

/** The cache key of the taps sent and not answered yet, with the newest answer per button. */
const PENDING_TAPS_KEY = 'quickMarkTaps';

interface PendingTaps {
  /** Taps in the order they were made; each is drawn on top of the directory. */
  taps: { key: string; markId: number }[];
  /** The newest answer per button among the taps of the current burst. */
  newest: Record<number, QuickMarkEvent>;
}

const NO_PENDING: PendingTaps = { taps: [], newest: {} };
const NO_MARKS: QuickMark[] = [];

function readDirectory(): Promise<QuickMark[]> {
  return api.quickMarksAPI.list();
}

/** The directory through the cache: Today's snapshot and the buttons share one request. */
export function readQuickMarks(): Promise<QuickMark[]> {
  return fetchQuery(QUICK_MARKS_KEY, readDirectory);
}

/** The first status that means the server failed rather than refused. */
const SERVER_ERROR_STATUS = 500;

/**
 * Send one tap, and once more under the same key if no answer came back.
 *
 * A connection that drops mid-send leaves the tab unable to tell a lost request
 * from a lost answer; the key makes the second attempt the same tap on the
 * server, so the day's sum cannot double. A refusal (4xx) is the server's
 * decision and is not asked again.
 */
async function sendTap(markId: number, key: string): Promise<QuickMarkEvent> {
  try {
    return await api.quickMarksAPI.tap(markId, {}, key);
  } catch (error) {
    if (error instanceof api.APIError && error.status < SERVER_ERROR_STATUS) throw error;
    return api.quickMarksAPI.tap(markId, {}, key);
  }
}

/**
 * The last tap of each button still on its way to the server.
 *
 * A button's taps go out one after another, not side by side: the server adds a
 * tap to the day's sum by reading it and writing it back, and two taps of one
 * button arriving together were seen to leave one step (2026-11-01, four parallel
 * POSTs moved the sum by one step). The screen does not wait for this queue — every
 * tap is drawn at once — so the order costs nothing the reader can see.
 */
const tapChains = new Map<number, Promise<unknown>>();

/**
 * How long a tap waits for the one before it. A request that hangs must not hold
 * every later tap of its button; past this the next one goes out anyway.
 */
export const TAP_TURN_WAIT_MS = 10_000;

function sendInTurn(markId: number, key: string): Promise<QuickMarkEvent> {
  // Only a tap still drawn as pending is waited for: after the session ended
  // (the cache, and with it the pending taps, cleared) an old chain holds nothing.
  const waiting = pendingTaps().taps.some((tap) => tap.markId === markId && tap.key !== key);
  const previous = waiting ? (tapChains.get(markId) ?? Promise.resolve()) : Promise.resolve();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const turn = Promise.race([
    previous,
    new Promise((resolve) => {
      timer = setTimeout(resolve, TAP_TURN_WAIT_MS);
    }),
  ]);
  // The previous tap's failure belongs to its own caller, who has already shown it.
  const mine = turn.then(
    () => sendTap(markId, key),
    () => sendTap(markId, key)
  );
  tapChains.set(markId, mine);
  const forget = () => {
    clearTimeout(timer);
    if (tapChains.get(markId) === mine) tapChains.delete(markId);
  };
  mine.then(forget, forget);
  return mine;
}

/** The directory with an answer folded in, untouched while there is no directory to fold into. */
function patchDirectory(patch: (marks: QuickMark[]) => QuickMark[]): void {
  if (getQueryData<QuickMark[]>(QUICK_MARKS_KEY) === undefined) return;
  setQueryData<QuickMark[]>(QUICK_MARKS_KEY, (marks = NO_MARKS) => patch(marks));
}

function pendingTaps(): PendingTaps {
  return getQueryData<PendingTaps>(PENDING_TAPS_KEY) ?? NO_PENDING;
}

/**
 * The quick-mark buttons of Today.
 *
 * Neither the order nor the `planned` flag is computed here. Both come from
 * `GET /quick-marks`, because the same selection serves the web, the floating
 * window of the agent and iOS — and an order computed in the browser would be
 * an order the other two do not have.
 *
 * A tap does not wait for the server: the button shows the tap at once, and the
 * request goes out behind it. Five quick taps are five requests and five drawn
 * steps; one that fails is taken off alone, the rest stay. The directory is not
 * read again for a tap — the answers carry the new sum.
 */
export function useQuickMarks({ onDayChanged }: UseQuickMarksOptions = {}): UseQuickMarksResult {
  const { state, refresh } = useQuery(QUICK_MARKS_KEY, readDirectory, { refreshOnVisible: true });
  const pending = useQueryData<PendingTaps>(PENDING_TAPS_KEY) ?? NO_PENDING;
  const [error, setError] = useState<string | null>(null);
  const [lastEvent, setLastEvent] = useState<QuickMarkEvent | null>(null);

  const directory = dataOr(state, NO_MARKS);
  const marks = pending.taps.reduce((list, tap) => applyQuickMarkTap(list, tap.markId), directory);

  const tellDayChanged = useCallback(
    (markId: number) => {
      const mark = getQueryData<QuickMark[]>(QUICK_MARKS_KEY)?.find((candidate) => candidate.id === markId);
      if (mark) onDayChanged?.(mark.category_id);
    },
    [onDayChanged]
  );

  const tap = useCallback(
    async (id: number) => {
      setError(null);
      const key = newTapKey();
      const before = pendingTaps();
      setQueryData<PendingTaps>(PENDING_TAPS_KEY, { ...before, taps: [...before.taps, { key, markId: id }] });

      let event: QuickMarkEvent;
      try {
        event = await sendInTurn(id, key);
      } catch (err) {
        const now = pendingTaps();
        setQueryData<PendingTaps>(PENDING_TAPS_KEY, {
          ...now,
          taps: now.taps.filter((candidate) => candidate.key !== key),
        });
        // The server's own sentence when it refused; a lost connection says
        // «Failed to fetch» in the browser's language, so it gets ours.
        setError(err instanceof api.APIError ? err.message : TAP_FAILED);
        return;
      }

      // The tap moves from the drawn layer into the directory in one step, so no
      // frame shows it twice or not at all.
      const now = pendingTaps();
      const taps = now.taps.filter((candidate) => candidate.key !== key);
      const known = now.newest[id];
      const newest = known === undefined || event.event_id > known.event_id ? event : known;
      const burstOver = !taps.some((candidate) => candidate.markId === id);
      const newestAfter = { ...now.newest, [id]: newest };
      if (burstOver) delete newestAfter[id];
      // Until the button's last tap is answered the answers may arrive out of
      // order, so the step is counted here; then the newest answer is the truth.
      patchDirectory((list) => (burstOver ? applyQuickMarkEvent(list, newest) : applyQuickMarkTap(list, id)));
      setQueryData<PendingTaps>(PENDING_TAPS_KEY, {
        taps,
        newest: newestAfter,
      });
      setLastEvent((previous) => (previous === null || event.event_id > previous.event_id ? event : previous));
      tellDayChanged(id);
    },
    [tellDayChanged]
  );

  const takeBack = useCallback(
    async (eventId: number): Promise<string | null> => {
      try {
        const undone = await api.quickMarksAPI.undo(eventId);
        patchDirectory((list) => applyQuickMarkUndo(list, undone));
        tellDayChanged(undone.quick_mark_id);
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
    [tellDayChanged]
  );

  const undo = useCallback(async () => {
    if (lastEvent === null) return;
    const refusal = await takeBack(lastEvent.event_id);
    if (refusal !== null) setError(refusal);
  }, [lastEvent, takeBack]);

  const reload = useCallback(() => {
    setError(null);
    void refresh();
  }, [refresh]);

  const clearError = useCallback(() => setError(null), []);

  return {
    marks,
    loading: state.status === 'loading',
    // Пустой справочник и недоступный справочник — разные вещи, но обе означают
    // «кнопок на экране нет». Ошибка показывается, список не выдумывается.
    error: error ?? errorMessage(state, TAP_FAILED),
    tap,
    lastEvent,
    undo,
    undoEvent: takeBack,
    reload,
    clearError,
  };
}
