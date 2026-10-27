'use client';
// [review:need-review] PHASE-01/61-today-total-owned-by-hook, PHASE-03/121, PHASE-03/124, PHASE-03/123, PHASE-01/174, PHASE-01/177, PHASE-01/206, PHASE-03/237, PHASE-03/247, PHASE-03/253
// summary: Today-screen state for both shells — the targeted re-read after a quick mark (the day's records, the ticks and the one streak that can have moved, newest answer wins), the first-round snapshot whose four reads run side by side (categories, the server's day, the records of a window around it, cut to that day, and the quick-mark directory) with the streaks moved to a second round that no longer blocks the buttons, the optimistic checklist flip and number increment each rolled back on its own failure, the quick-mark tap that repaints from its own answer and retries a dropped send under the key of the first attempt, and the undo of the last tap
// summary: useToday takes its day from GET /day-mode (the server's current day), not the browser clock: the header date, the records read, the targeted re-read, the checklist tick and the number increment all use it; the day is read again with the snapshot when the tab returns and on a one-minute timer for a tab that stays in front across the boundary; only the newest snapshot is applied, a tick saved for a finished day is not shown in the new one, and increments of a finished day are dropped; a day that cannot be read leaves date empty and the screen without data
// summary: #247/#253 — one read of the day per moment shared by the snapshot, the minute timer and the day-mode badge (dayModeClient); the records no longer wait for the day; a day not confirmed (last snapshot read failed, or three minute reads in a row did) refuses ticks and increments and is said in the banner once; a failed tick rolls back only on the day it was written for; the timer's answer after unmount is dropped and its retry of a failed first load does not raise the banner again

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRefreshOnVisible } from '@/hooks/useRefreshOnVisible';
import type { DayModeClient } from '@/hooks/useDayMode';
import { todayISO } from '@/lib/date';
import { shiftDay } from '@/lib/server-day';
// A namespace import read at call time, as in `useDayMode`: suites that mock
// `@/lib/api` with a fixed list of names must still link every screen of Today.
import * as api from '@/lib/api';
import {
  categoriesAPI,
  entriesAPI,
  quickMarksAPI,
  type Category,
  type DayMode,
  type Entry,
  type EntryCreate,
  type QuickMark,
  type QuickMarkEvent,
} from '@/lib/api';
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
 * How often a page that stays open asks the server which day it is running.
 *
 * A tab that never loses focus gets no visibility event at the day boundary, and
 * until it learns the new day every tick and increment would be written to the
 * old one. One light read a minute bounds that gap; the full snapshot is taken
 * only when the answer differs.
 */
export const DAY_RECHECK_MS = 60_000;

/**
 * How many one-minute reads of the day in a row may fail before the screen says
 * the day is not being followed and stops writing to the day it last knew.
 */
export const DAY_POLL_FAILURES_LIMIT = 3;

/**
 * What the error banner says while the day is not confirmed by the server.
 *
 * A tick or an increment written now would go to the day this screen last
 * heard of, which may have ended: the same rule as for the day-mode badge.
 */
export const DAY_UNCONFIRMED = 'День не подтверждён сервером: запись приостановлена, пока не вернётся связь';

/** The records window around the day the screen expects, in days on each side. */
const ENTRIES_WINDOW_SPREAD_DAYS = 1;

/**
 * The explicit page size of the records window, as the dashboard asks its own.
 * The server's default (100) fills up at about 35 records a day over three days,
 * and a full page may have lost its tail: it is then read again for the day alone.
 */
const ENTRIES_WINDOW_LIMIT = 1000;

/**
 * What the streak section says when its own round failed.
 *
 * Its own sentence rather than the screen's error: the buttons are on screen
 * and working, and the only thing missing is the number of days.
 */
export const STREAKS_FAILED = 'Стрики не загрузились';

/** Everything a Today screen needs; the two shells differ only in markup. */
export interface UseTodayResult {
  /**
   * The day the server is running, as `YYYY-MM-DD`; empty until its first
   * answer. The browser's own clock is never consulted: between midnight and
   * the boundary hour, or in another zone, it names a different day.
   */
  date: string;
  /**
   * The day is not confirmed by the server right now (the last full read of it
   * failed, or several minute reads in a row did): writes are refused until one
   * read goes through.
   */
  dayStale: boolean;
  /**
   * The client the day-mode badge reads the day through. Pass it to
   * `useDayMode`: the badge then shares the read of the day with this hook —
   * one request, one answer — and cannot name another day than the header.
   */
  dayModeClient: DayModeClient;
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
  /** Optimistically patch one confirmed entry, restoring it if PATCH fails. */
  updateEntry: (entry: Entry, data: Partial<EntryCreate>) => Promise<Entry>;
  /** Optimistically remove one confirmed row, restoring it if DELETE fails. */
  deleteEntry: (entry: Entry) => Promise<boolean>;
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
  /**
   * Re-read what one quick mark can have changed: today's records, the ticks
   * built from them and — only when the mark's category counts a streak of
   * days avoided — that category's streak.
   *
   * The categories and the button directory are left alone: a tap leaves them
   * as they were, and re-reading them would turn each of five quick taps into
   * four requests. Overlapping calls are safe — only the newest answer is
   * applied, so a slow response to the third tap cannot put back the day as
   * the second tap left it.
   */
  reloadAfterMark: (categoryId: number) => Promise<void>;
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
  // The server's day, also kept in a ref: the writes and the targeted re-read are
  // stable callbacks that must see the day of the latest snapshot.
  const [day, setDay] = useState('');
  const dayRef = useRef('');
  // The day is not confirmed (see `dayStale`); the ref is what the stable write callbacks read.
  const [dayStale, setDayStale] = useState(false);
  const dayStaleRef = useRef(false);
  const pollFailures = useRef(0);
  // The one read of GET /day-mode in flight: the snapshot, the minute timer and
  // the day-mode badge join it instead of each asking and possibly hearing a
  // different day around the boundary.
  const inflightDay = useRef<Promise<DayMode> | null>(null);
  // Snapshots started and not yet finished: the badge must not start another one.
  const loadsInFlight = useRef(0);
  // The newest snapshot read; an older one still in flight is stale and must not
  // put the day back or wipe what the new day has already collected.
  const loadSeq = useRef(0);
  // The newest re-read after a mark; an older one still in flight is stale.
  const markReadSeq = useRef(0);
  const [checked, setChecked] = useState<CheckedMap>({});
  const [streaks, setStreaks] = useState<StreakMap>({});
  const [loading, setLoading] = useState(true);
  const [streaksLoading, setStreaksLoading] = useState(true);
  const [streaksError, setStreaksError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  /**
   * Ask the server for its day. A snapshot always asks anew and becomes the
   * read the others join (an older read still in flight may be stuck, and a
   * snapshot must not wait behind it); the minute timer and the badge join
   * the read in flight, if there is one, and start it otherwise.
   */
  const readDay = useCallback((fresh: boolean): Promise<DayMode> => {
    if (!fresh && inflightDay.current !== null) return inflightDay.current;
    const tracked: Promise<DayMode> = api.agentAPI.dayMode().finally(() => {
      if (inflightDay.current === tracked) inflightDay.current = null;
    });
    inflightDay.current = tracked;
    return tracked;
  }, []);

  /**
   * Raise or retire the «day not confirmed» state. The banner is set once, on
   * the way in: a banner the user closed does not come back with every poll.
   */
  const setStale = useCallback((stale: boolean) => {
    if (dayStaleRef.current === stale) return;
    dayStaleRef.current = stale;
    setDayStale(stale);
    if (stale) setError(DAY_UNCONFIRMED);
    else setError((previous) => (previous === DAY_UNCONFIRMED ? null : previous));
  }, []);

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
      const loaded = await loadStreaks(avoidIds, () => categoriesAPI.getStreaks('avoid'));
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

  /**
   * Take a server snapshot of today's records as the screen's own.
   *
   * Whatever the snapshot now carries is no longer this session's to hold;
   * dropping it from the local copies is what keeps a saved increment from
   * being counted twice.
   */
  const adoptEntries = useCallback((categoriesData: Category[], entriesData: Entry[]) => {
    setEntries(entriesData);
    const fetchedIds = new Set(entriesData.map((entry) => entry.id));
    setOptimisticEntries((prev) => prev.filter((entry) => !fetchedIds.has(entry.id)));
    setChecked(buildCheckedMap(categoriesData, entriesData));
  }, []);

  /**
   * Fetch the whole Today snapshot: the server's day and the records around it,
   * side by side.
   *
   * The records do not wait for the day. They are asked for a window of three
   * days around the day this screen expects (the last one it knew, the browser's
   * on the first load) and cut to the server's day when both have arrived. The
   * browser's clock is only a hint for the window: a server day outside it, or a
   * page that may have lost its tail, costs one exact read, never a wrong day.
   *
   * `showSpinner` is the difference between the first load (nothing on screen
   * yet, so a spinner is the honest state) and a background refetch — the tab
   * returning, the day-boundary timer, a save that asks for a fresh read: there
   * the old snapshot stays rendered until the new one lands, so flipping
   * `loading` would blank a screen the user is already looking at. `quiet` is a
   * retry nobody asked for: its failure does not raise the banner again.
   *
   * Only the newest call is applied. An older one that lands late would put the
   * day back and wipe the increments the new day already holds.
   */
  const loadData = useCallback(async ({ showSpinner = false, quiet = false } = {}) => {
    loadSeq.current += 1;
    loadsInFlight.current += 1;
    const mine = loadSeq.current;
    try {
      if (showSpinner) setLoading(true);
      const hint = dayRef.current !== '' ? dayRef.current : todayISO();
      const windowStart = shiftDay(hint, -ENTRIES_WINDOW_SPREAD_DAYS);
      const windowEnd = shiftDay(hint, ENTRIES_WINDOW_SPREAD_DAYS);
      const dayRead = readDay(true).then(
        ({ date }) => {
          pollFailures.current = 0;
          if (mine === loadSeq.current) setStale(false);
          return date;
        },
        (err: unknown) => {
          // A day that was known and cannot be confirmed now may have ended.
          if (mine === loadSeq.current && dayRef.current !== '') setStale(true);
          throw err;
        }
      );
      const [categoriesData, date, windowEntries, quickMarksData] = await Promise.all([
        categoriesAPI.getAll(),
        dayRead,
        entriesAPI.getAll({ startDate: windowStart, endDate: windowEnd, limit: ENTRIES_WINDOW_LIMIT }),
        quickMarksAPI.list(),
      ]);
      const windowFits =
        date >= windowStart && date <= windowEnd && windowEntries.length < ENTRIES_WINDOW_LIMIT;
      const entriesData = windowFits
        ? windowEntries.filter((entry) => entry.entry_date === date)
        : await entriesAPI.getAll({ startDate: date, endDate: date });
      if (mine !== loadSeq.current) return;
      // Increments of a day that has ended are not part of the new one.
      if (dayRef.current !== '' && dayRef.current !== date) setOptimisticEntries([]);
      dayRef.current = date;
      setDay(date);
      setCategories(categoriesData);
      setQuickMarks(quickMarksData);
      // The snapshot is the server's, not this session's: whatever tap the
      // «Отменить» affordance pointed at is now indistinguishable from the rest
      // of the day, so the offer goes with it.
      setLastQuickMarkEvent(null);
      adoptEntries(categoriesData, entriesData);
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
      if (mine === loadSeq.current && !quiet) {
        setError(err instanceof Error ? err.message : 'Failed to load today data');
      }
    } finally {
      loadsInFlight.current -= 1;
      // A newer snapshot owns the spinner too.
      if (mine === loadSeq.current) setLoading(false);
    }
  }, [adoptEntries, refreshStreaks, readDay, setStale]);

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

  const reloadAfterMark = useCallback(
    async (categoryId: number) => {
      const category = categories.find((candidate) => candidate.id === categoryId);
      // Started before the records are awaited, so the two reads run side by
      // side: the streak does not wait behind the list it will be shown beside.
      const streak = category?.streak_mode === 'avoid' ? reloadStreak(categoryId) : null;

      markReadSeq.current += 1;
      const mine = markReadSeq.current;
      try {
        const date = dayRef.current;
        const fresh = await entriesAPI.getAll({ startDate: date, endDate: date });
        // A read of a day that has ended since is not the screen's any more.
        if (mine === markReadSeq.current && date === dayRef.current) {
          adoptEntries(categories, fresh);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to refresh today');
      }
      await streak;
    },
    [categories, adoptEntries, reloadStreak]
  );

  useEffect(() => {
    loadData({ showSpinner: true });
  }, [loadData]);

  const refresh = useCallback(() => {
    void loadData();
  }, [loadData]);

  // Standalone PWA never reloads the document, so /m/today would otherwise keep
  // rendering the snapshot fetched when the app was launched.
  useRefreshOnVisible(refresh);

  // False once the screen is gone: a read answered after that must not start a snapshot.
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  // A tab that stays in front across the day boundary: see DAY_RECHECK_MS.
  useEffect(() => {
    // The newest minute read, and whether it is still unanswered.
    let pollSeq = 0;
    let pollPending = false;
    const timer = setInterval(() => {
      if (document.visibilityState === 'hidden') return;
      // No day yet: the first snapshot failed, and this tick is its retry.
      if (dayRef.current === '') {
        void loadData({ quiet: true });
        return;
      }
      // A read still unanswered a minute later is a lost read, and the next one asks anew:
      // joining a request that hangs would leave the screen writing to a day nobody confirms.
      const hung = pollPending;
      if (hung) countPollFailure();
      pollSeq += 1;
      const mine = pollSeq;
      pollPending = true;
      readDay(hung).then(
        ({ date }) => {
          if (mine === pollSeq) pollPending = false;
          if (!mounted.current) return;
          pollFailures.current = 0;
          setStale(false);
          // A snapshot on its way is already moving the screen to this day.
          if (date !== dayRef.current && loadsInFlight.current === 0) void loadData();
        },
        () => {
          if (mine !== pollSeq) return;
          pollPending = false;
          if (mounted.current) countPollFailure();
        }
      );
    }, DAY_RECHECK_MS);

    function countPollFailure() {
      // One lost read is not news about the day; several in a row are.
      pollFailures.current += 1;
      if (pollFailures.current >= DAY_POLL_FAILURES_LIMIT) setStale(true);
    }
    return () => clearInterval(timer);
  }, [loadData, readDay, setStale]);

  // The badge reads the day through the same promise; if its answer is a day this
  // screen has not moved to and no snapshot is on the way, the screen moves.
  const dayModeClient = useMemo<DayModeClient>(
    () => ({
      read: async () => {
        const mode = await readDay(false);
        if (
          mounted.current &&
          loadsInFlight.current === 0 &&
          dayRef.current !== '' &&
          mode.date !== dayRef.current
        ) {
          void loadData();
        }
        return mode;
      },
      set: (date, draft) => api.agentAPI.setDayMode(date, draft),
      clear: (date) => api.agentAPI.clearDayMode(date),
    }),
    [readDay, loadData]
  );

  const toggleField = useCallback(
    async (categoryId: number, fieldId: number) => {
      if (dayStaleRef.current || dayRef.current === '') {
        setError(DAY_UNCONFIRMED);
        return;
      }
      const writtenDay = dayRef.current;
      const current = isFieldChecked(checked, categoryId, fieldId);
      const next = !current;

      setChecked((prev) => setFieldChecked(prev, categoryId, fieldId, next));

      try {
        const saved = await entriesAPI.upsertChecklist({
          category_id: categoryId,
          entry_date: writtenDay,
          values: { [fieldId]: next },
        });
        // A tick that was answered after the day changed belongs to the day it was
        // written for, not to the list now on screen.
        if (saved.entry_date === dayRef.current) {
          setEntries((previous) => {
            const hasSaved = previous.some((entry) => entry.id === saved.id);
            return hasSaved
              ? previous.map((entry) => entry.id === saved.id ? saved : entry)
              : [...previous, saved];
          });
        }
      } catch (err) {
        // The map now belongs to the new day if the day moved: the field of
        // yesterday's list has nothing to put back there.
        if (dayRef.current === writtenDay) {
          setChecked((prev) => setFieldChecked(prev, categoryId, fieldId, current));
        }
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
      if (dayStaleRef.current || dayRef.current === '') {
        setError(DAY_UNCONFIRMED);
        return false;
      }
      const localId = nextOptimisticId.current;
      nextOptimisticId.current -= 1;
      const entryDate = dayRef.current;

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

  const updateEntry = useCallback(
    async (entry: Entry, data: Partial<EntryCreate>): Promise<Entry> => {
      const optimistic: Entry = {
        ...entry,
        entry_date: data.entry_date ?? entry.entry_date,
        notes: data.notes ?? entry.notes,
        values: data.values?.map((value, index) => {
          const previous = entry.values.find((candidate) => candidate.field_id === value.field_id);
          return {
            id: previous?.id ?? -(index + 1),
            entry_id: entry.id,
            field_id: value.field_id,
            value: value.value,
          };
        }) ?? entry.values,
      };
      const wasFetched = entries.some((candidate) => candidate.id === entry.id);
      const wasOptimistic = optimisticEntries.some((candidate) => candidate.id === entry.id);
      const replace = (candidate: Entry) => candidate.id === entry.id ? optimistic : candidate;
      setEntries((previous) => previous.map(replace));
      setOptimisticEntries((previous) => previous.map(replace));

      try {
        const saved = await entriesAPI.update(entry.id, data);
        const persist = (candidate: Entry) => candidate.id === entry.id ? saved : candidate;
        setEntries((previous) => previous.map(persist));
        setOptimisticEntries((previous) => previous.map(persist));
        return saved;
      } catch (err) {
        if (wasFetched) {
          setEntries((previous) =>
            previous.map((candidate) => candidate.id === entry.id ? entry : candidate)
          );
        }
        if (wasOptimistic) {
          setOptimisticEntries((previous) =>
            previous.map((candidate) => candidate.id === entry.id ? entry : candidate)
          );
        }
        setError(err instanceof Error ? err.message : 'Failed to update entry');
        throw err;
      }
    },
    [entries, optimisticEntries]
  );

  /**
   * Delete only a server-owned entry. A quick add begins with a negative local
   * id, and offering DELETE for that placeholder would make the list promise
   * an operation the server cannot possibly perform.
   */
  const deleteEntry = useCallback(
    async (entry: Entry): Promise<boolean> => {
      if (entry.id <= 0) return false;

      const wasFetched = entries.some((candidate) => candidate.id === entry.id);
      const wasOptimistic = optimisticEntries.some((candidate) => candidate.id === entry.id);
      setEntries((previous) => previous.filter((candidate) => candidate.id !== entry.id));
      setOptimisticEntries((previous) =>
        previous.filter((candidate) => candidate.id !== entry.id)
      );

      try {
        await entriesAPI.delete(entry.id);
        if (
          categories.find((category) => category.id === entry.category_id)
            ?.streak_mode === "avoid"
        ) {
          await reloadStreak(entry.category_id);
        }
        return true;
      } catch (err) {
        if (wasFetched) {
          setEntries((previous) =>
            previous.some((candidate) => candidate.id === entry.id)
              ? previous
              : [...previous, entry]
          );
        }
        if (wasOptimistic) {
          setOptimisticEntries((previous) =>
            previous.some((candidate) => candidate.id === entry.id)
              ? previous
              : [...previous, entry]
          );
        }
        setError(err instanceof Error ? err.message : 'Failed to delete entry');
        return false;
      }
    },
    [categories, entries, optimisticEntries, reloadStreak]
  );

  const groups = partitionTodayCategories(categories);
  const nothingToTrack =
    quickMarks.length === 0 &&
    groups.avoid.length === 0 &&
    groups.checklist.length === 0 &&
    groups.quickForm.length === 0;

  return {
    date: day,
    dayStale,
    dayModeClient,
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
    updateEntry,
    deleteEntry,
    tapQuickMark,
    lastQuickMarkEvent,
    undoLastQuickMark,
    reloadStreak,
    reload,
    reloadAfterMark,
  };
}
