'use client';
// [review:need-review] PHASE-01/61-today-total-owned-by-hook, PHASE-03/121, PHASE-03/124, PHASE-03/123
// summary: Today-screen state for both shells — the snapshot fetched in one round (categories, entries and the quick-mark directory) with the streaks moved to a second round that no longer blocks the buttons, the optimistic checklist flip and number increment each rolled back on its own failure, the quick-mark tap that repaints from its own answer and retries a dropped send under the key of the first attempt, and the undo of the last tap

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRefreshOnVisible } from '@/hooks/useRefreshOnVisible';
import {
  categoriesAPI,
  entriesAPI,
  quickMarksAPI,
  type Category,
  type Entry,
  type QuickMark,
  type QuickMarkEvent,
} from '@/lib/api';
import { todayISO } from '@/lib/date';
import { partitionTodayCategories, type TodayGroups } from '@/lib/today-categories';
import { applyQuickMarkEvent, applyQuickMarkUndo, newTapKey } from '@/lib/quick-marks';
import {
  buildCheckedMap,
  isFieldChecked,
  loadStreaks,
  mergeOptimisticEntries,
  optimisticNumberEntry,
  setFieldChecked,
  type CheckedMap,
  type StreakMap,
} from '@/lib/today-entries';

/**
 * What the streak section says when its own round failed.
 *
 * Its own sentence rather than the screen's error: the buttons are on screen
 * and working, and the only thing missing is the number of days.
 */
export const STREAKS_FAILED = 'Стрики не загрузились';

/** Everything a Today screen needs; the two shells differ only in markup. */
export interface UseTodayResult {
  date: string;
  entries: Entry[];
  /**
   * Every active category, ungrouped.
   *
   * `groups` routes categories to widgets; the challenge form needs the plain
   * list, because a rule may point at a category no Today widget shows.
   */
  categories: Category[];
  groups: TodayGroups;
  /**
   * The quick-mark directory with today's state on it, in the order the server
   * gave. Empty is the normal starting state — buttons are entered by hand —
   * and an empty list means the screen shows no quick-mark section at all.
   */
  quickMarks: QuickMark[];
  checked: CheckedMap;
  streaks: StreakMap;
  /**
   * The first round is done: categories, entries and the buttons are on screen.
   *
   * Not "everything has arrived". The streaks are a second round and report
   * themselves through `streaksLoading`, because a screen that waits for them
   * is a screen with no buttons on it for the length of two serial round trips
   * — and pressing a button is the reason the tab was opened.
   */
  loading: boolean;
  /** The streaks round is still in flight; the rest of the screen is live. */
  streaksLoading: boolean;
  /**
   * Why the streaks round failed, or null.
   *
   * Kept apart from `error` so the failure can be drawn inside the streak
   * section: a banner over the whole screen for a streak that did not load
   * would take the buttons away over something that is not about them.
   */
  streaksError: string | null;
  error: string | null;
  /** True when no category routes to any Today widget. */
  nothingToTrack: boolean;
  setError: (message: string | null) => void;
  /** Optimistically flip a checklist field, rolling back if the save fails. */
  toggleField: (categoryId: number, fieldId: number) => Promise<void>;
  /**
   * Log one number entry, showing it in `entries` before the request resolves
   * and withdrawing exactly that increment if the request fails. Resolves false
   * on failure, so the caller can keep whatever it would have to retype.
   */
  addNumber: (categoryId: number, fieldId: number, amount: number) => Promise<boolean>;
  /**
   * Tap one quick mark. What the button means is the server's answer, so the
   * id is all that is sent; the response carries the new total and the screen
   * repaints from it without a second request.
   */
  tapQuickMark: (quickMarkId: number) => Promise<void>;
  /**
   * The tap this session made last and has not taken back, or null. What the
   * «Отменить» affordance is drawn from; cleared once it is used, and cleared
   * by a refetch, because a snapshot from the server is a state this session
   * did not produce and cannot claim the last tap of.
   */
  lastQuickMarkEvent: QuickMarkEvent | null;
  /**
   * Take the last tap back — one action, no trip to the entry editor.
   *
   * A refusal (the value was edited by hand, the tap is no longer the last one)
   * comes back as the server's sentence in `error` and retires the affordance:
   * the tap it pointed at is not undoable any more, and offering it again would
   * be a button that answers 409 forever.
   */
  undoLastQuickMark: () => Promise<void>;
  /** Re-fetch one avoid category's streak, e.g. after a relapse was logged. */
  reloadStreak: (categoryId: number) => Promise<void>;
  /**
   * Re-fetch the whole snapshot without blanking the screen — what a full entry
   * editor calls once it has saved, since its edit can touch any field.
   */
  reload: () => Promise<void>;
}

export function useToday(): UseTodayResult {
  const [categories, setCategories] = useState<Category[]>([]);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [quickMarks, setQuickMarks] = useState<QuickMark[]>([]);
  const [lastQuickMarkEvent, setLastQuickMarkEvent] = useState<QuickMarkEvent | null>(
    null
  );
  // Entries this session logged that the last snapshot did not (yet) contain:
  // in flight, or saved after the snapshot was taken. Kept apart from `entries`
  // so a refetch can replace the snapshot without discarding them.
  const [optimisticEntries, setOptimisticEntries] = useState<Entry[]>([]);
  const nextOptimisticId = useRef(-1);
  const [checked, setChecked] = useState<CheckedMap>({});
  const [streaks, setStreaks] = useState<StreakMap>({});
  const [loading, setLoading] = useState(true);
  const [streaksLoading, setStreaksLoading] = useState(true);
  const [streaksError, setStreaksError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  /**
   * Fetch the whole Today snapshot.
   *
   * `showSpinner` is the difference between the first load (nothing on screen
   * yet, so a spinner is the honest state) and a background refetch triggered
   * by the tab becoming visible again: there the old snapshot stays rendered
   * until the new one lands, so flipping `loading` would blank a screen the
   * user is already looking at.
   */
  /**
   * The second round: one streak per avoid category.
   *
   * Separate from the snapshot rather than folded into it, because it is the
   * only part of Today that scales with the number of categories, and the
   * buttons must not wait behind it. A category with no avoid streak at all
   * finishes it immediately — an empty list is a finished round, not a pending
   * one.
   */
  const refreshStreaks = useCallback(async (avoidIds: number[]) => {
    setStreaksLoading(true);
    setStreaksError(null);
    try {
      const loaded = await loadStreaks(avoidIds, (id) => categoriesAPI.getStreak(id));
      setStreaks(loaded.streaks);
      // Упавший запрос раньше был молчаливым «—» в карточке. Секция обязана
      // сказать, что цифры нет потому, что запрос не дошёл, а не потому, что
      // стрик нулевой.
      setStreaksError(loaded.failed.length > 0 ? STREAKS_FAILED : null);
    } catch (err) {
      setStreaksError(err instanceof Error ? err.message : STREAKS_FAILED);
    } finally {
      setStreaksLoading(false);
    }
  }, []);

  const loadData = useCallback(async ({ showSpinner = false } = {}) => {
    try {
      if (showSpinner) setLoading(true);
      const date = todayISO();
      const [categoriesData, entriesData, quickMarksData] = await Promise.all([
        categoriesAPI.getAll(),
        entriesAPI.getAll({ startDate: date, endDate: date }),
        // No date is sent: which day is running is the server's answer, and a
        // browser computing its own would disagree with it between midnight
        // and the boundary hour.
        quickMarksAPI.list(),
      ]);
      setCategories(categoriesData);
      setEntries(entriesData);
      setQuickMarks(quickMarksData);
      // The snapshot is the server's, not this session's: whatever tap the
      // «Отменить» affordance pointed at is now indistinguishable from the rest
      // of the day, so the offer goes with it.
      setLastQuickMarkEvent(null);
      // Whatever the snapshot now carries is no longer ours to hold; dropping it
      // here is what keeps a saved increment from being counted twice.
      const fetchedIds = new Set(entriesData.map((entry) => entry.id));
      setOptimisticEntries((prev) => prev.filter((entry) => !fetchedIds.has(entry.id)));
      setChecked(buildCheckedMap(categoriesData, entriesData));
      // A silent refetch that succeeds must retire the previous failure, or the
      // error banner outlives the outage that caused it.
      setError(null);

      // Второй круг. Раньше он стоял здесь же под `await`, и экран ждал его,
      // прежде чем показать хоть одну кнопку: стрики читаются по категории,
      // то есть это N запросов после того, как первый круг уже вернулся.
      // Ошибка второго круга живёт в своей секции и кнопок не убирает.
      const avoidIds = partitionTodayCategories(categoriesData).avoid.map(
        ({ category }) => category.id
      );
      void refreshStreaks(avoidIds);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load today data');
    } finally {
      setLoading(false);
    }
  }, [refreshStreaks]);

  const reload = useCallback(async () => {
    await loadData();
  }, [loadData]);

  /**
   * One tap, one call. The answer already carries `today_total` and `done` for
   * the button that was pressed, so the directory is patched from it rather
   * than fetched again — that single request is what the acceptance case
   * measures on the network log.
   */
  const tapQuickMark = useCallback(async (quickMarkId: number) => {
    // One key for both attempts. A connection that drops mid-send leaves this
    // tab unable to tell a lost request from a lost answer, and a second tap
    // under a fresh key would be a second tap: the sum of the day would double
    // on exactly the flaky network the retry exists for.
    const key = newTapKey();
    try {
      let event: QuickMarkEvent;
      try {
        event = await quickMarksAPI.tap(quickMarkId, {}, key);
      } catch {
        event = await quickMarksAPI.tap(quickMarkId, {}, key);
      }
      setQuickMarks((prev) => applyQuickMarkEvent(prev, event));
      setLastQuickMarkEvent(event);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to record the mark');
    }
  }, []);

  const undoLastQuickMark = useCallback(async () => {
    const event = lastQuickMarkEvent;
    if (event === null) return;
    try {
      const undone = await quickMarksAPI.undo(event.event_id);
      setQuickMarks((prev) => applyQuickMarkUndo(prev, undone));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to undo the mark');
    } finally {
      setLastQuickMarkEvent(null);
    }
  }, [lastQuickMarkEvent]);

  const reloadStreak = useCallback(async (categoryId: number) => {
    const streak = await categoriesAPI.getStreak(categoryId).catch(() => null);
    setStreaks((prev) => ({ ...prev, [categoryId]: streak }));
  }, []);

  useEffect(() => {
    loadData({ showSpinner: true });
  }, [loadData]);

  const refresh = useCallback(() => {
    void loadData();
  }, [loadData]);

  // Standalone PWA never reloads the document, so /m/today would otherwise keep
  // rendering the snapshot fetched when the app was launched.
  useRefreshOnVisible(refresh);

  const toggleField = useCallback(
    async (categoryId: number, fieldId: number) => {
      const current = isFieldChecked(checked, categoryId, fieldId);
      const next = !current;

      setChecked((prev) => setFieldChecked(prev, categoryId, fieldId, next));

      try {
        await entriesAPI.upsertChecklist({
          category_id: categoryId,
          entry_date: todayISO(),
          values: { [fieldId]: next },
        });
      } catch (err) {
        setChecked((prev) => setFieldChecked(prev, categoryId, fieldId, current));
        setError(err instanceof Error ? err.message : 'Failed to save check');
      }
    },
    [checked]
  );

  /**
   * One tap, one entry, no in-flight lock: five taps are five increments, and a
   * failure among them withdraws only its own — the rest stay banked.
   */
  const addNumber = useCallback(
    async (categoryId: number, fieldId: number, amount: number): Promise<boolean> => {
      const localId = nextOptimisticId.current;
      nextOptimisticId.current -= 1;
      const entryDate = todayISO();

      setOptimisticEntries((prev) => [
        ...prev,
        optimisticNumberEntry({ id: localId, categoryId, fieldId, entryDate, amount }),
      ]);

      try {
        const saved = await entriesAPI.create({
          category_id: categoryId,
          entry_date: entryDate,
          values: [{ field_id: fieldId, value: String(amount) }],
        });
        // Adopt the server id so the snapshot that first returns this row
        // reclaims it. The local values are kept as they are: the increment on
        // screen must not shift because the response spelled it differently.
        setOptimisticEntries((prev) =>
          prev.map((entry) => (entry.id === localId ? { ...entry, id: saved.id } : entry))
        );
        return true;
      } catch (err) {
        setOptimisticEntries((prev) => prev.filter((entry) => entry.id !== localId));
        setError(err instanceof Error ? err.message : 'Failed to save entry');
        return false;
      }
    },
    []
  );

  const groups = partitionTodayCategories(categories);
  const nothingToTrack =
    quickMarks.length === 0 &&
    groups.avoid.length === 0 &&
    groups.checklist.length === 0 &&
    groups.quickForm.length === 0;

  return {
    date: todayISO(),
    entries: mergeOptimisticEntries(entries, optimisticEntries),
    categories,
    groups,
    quickMarks,
    checked,
    streaks,
    loading,
    streaksLoading,
    streaksError,
    error,
    nothingToTrack,
    setError,
    toggleField,
    addNumber,
    tapQuickMark,
    lastQuickMarkEvent,
    undoLastQuickMark,
    reloadStreak,
    reload,
  };
}
