'use client';
// [review:need-review] PHASE-01/28-today-avoid-card, PHASE-01/201, PHASE-01/177, PHASE-01/207
// summary: Today avoid streak card — «Случилось» records a relapse of any avoid category in one tap through the relapse endpoint (the server decides what to write), refreshes the streak and the day list, offers an undo only of a relapse this card wrote (kept when a repeated tap lands on it), and optional details (how many above zero, a note) afterwards, and the card itself links to the category page of the current shell

import { useId, useRef, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { AlertCircle, ChevronRight, Flame } from 'lucide-react';
import {
  categoriesAPI,
  entriesAPI,
  type Category,
  type CategoryStreak,
  type Entry,
  type EntryCreate,
  type Field,
  type RelapseRecorded,
} from '@/lib/api';
import { FieldValueInput } from '@/components/FieldValueInput';
import { formatCleanDays, formatDays } from '@/lib/streak-format';
import { newTapKey } from '@/lib/quick-marks';
import { orderedFields } from '@/lib/today-categories';
import { isMobilePath, toMobilePath } from '@/lib/view-mode';
import { entryInputClass } from '@/lib/ui-constants';

interface AvoidStreakCardProps {
  category: Category;
  /** The "how much" number field the details step records the amount into. */
  numberField?: Field;
  /**
   * Not read since #207: whether today broke the streak is the server's answer
   * (`streak`), not a rule re-derived here from the day's entries. Optional so
   * the Today screens can stop passing it.
   */
  entries?: Entry[];
  /** Streak data, or null while loading / when the endpoint failed. */
  streak: CategoryStreak | null;
  /** Called after a relapse is recorded, undone or edited so the parent refetches the streak. */
  onRelapse: (categoryId: number) => void | Promise<void>;
  /** Replaces the day's entry snapshot after any of those. */
  onEntriesChanged: () => Promise<void>;
  onError: (message: string) => void;
  /** Opens the day list without treating it as a relapse. */
  onOpenEntries?: () => void;
}

/**
 * Where the card is in its one job: record a relapse, then optionally undo it
 * or add details to it. The entry is the one the tap landed on; undo is offered
 * only when the tap wrote it (`created`), so it never deletes a relapse a quick
 * mark or another tab recorded a moment earlier.
 */
type RelapseState =
  | { phase: 'idle' }
  | { phase: 'recording' }
  | { phase: 'recorded'; entry: RelapseRecorded }
  | { phase: 'details'; entry: RelapseRecorded }
  | { phase: 'undoing'; entry: RelapseRecorded }
  | { phase: 'saving-details'; entry: RelapseRecorded };

const RECORD_FAILED = 'Не удалось записать срыв';
const UNDO_FAILED = 'Не удалось отменить срыв';
const DETAILS_FAILED = 'Не удалось сохранить подробности';
// Zero of a count or of time spent is what a clean day records: saved over the
// tap, it would quietly turn the relapse into one.
const AMOUNT_NOT_POSITIVE = 'Сколько — больше нуля, или оставьте поле пустым';
const ENTRIES_REFRESH_FAILED = 'Список записей не обновился';

const BUTTON_CLASS =
  'inline-flex min-h-11 items-center gap-2 px-4 py-2.5 rounded-full text-sm font-medium bg-surface border border-white/10 text-text-secondary transition-all duration-200 hover:text-text-primary hover:border-white/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-lime disabled:opacity-50';

/** The details step's "how much": the number field, else the first duration. */
function amountFieldOf(category: Category, numberField: Field | undefined): Field | undefined {
  return numberField ?? orderedFields(category).find((field) => field.field_type === 'duration');
}

/**
 * The entry a tap landed on, as the card should hold it. A repeated tap within
 * the minute gets this tab's own relapse back with `created: false`; it is still
 * the relapse this card wrote, so the undo stays.
 */
function landedEntry(previous: RelapseState, entry: RelapseRecorded): RelapseRecorded {
  const ownedBefore =
    previous.phase !== 'idle' &&
    previous.phase !== 'recording' &&
    previous.entry.id === entry.id &&
    previous.entry.created;
  return ownedBefore ? { ...entry, created: true } : entry;
}

/** The category page in the shell the card is shown in, so /m/today stays inside /m. */
function categoryHref(pathname: string, categoryId: number): string {
  const desktop = `/categories/${categoryId}`;
  return isMobilePath(pathname) ? (toMobilePath(desktop) ?? desktop) : desktop;
}

export default function AvoidStreakCard({
  category,
  numberField,
  streak,
  onRelapse,
  onEntriesChanged,
  onError,
  onOpenEntries,
}: AvoidStreakCardProps) {
  const pathname = usePathname();
  const [state, setState] = useState<RelapseState>({ phase: 'idle' });
  const [amount, setAmount] = useState('');
  const [note, setNote] = useState('');
  // State lags a render behind a click; the ref stops the second click of a
  // double tap synchronously, before the button has re-rendered as disabled.
  const busy = useRef(false);
  // Kept across a failed attempt, so the retry is the same request to the
  // server and not a second relapse.
  const tapKey = useRef<string | null>(null);
  const amountId = useId();
  const noteId = useId();

  const amountField = amountFieldOf(category, numberField);
  const working =
    state.phase === 'recording' || state.phase === 'undoing' || state.phase === 'saving-details';

  /** Streak first: the counter is what the tap is for, the day list follows. */
  const refresh = async () => {
    await onRelapse(category.id);
    try {
      await onEntriesChanged();
    } catch {
      onError(ENTRIES_REFRESH_FAILED);
    }
  };

  const run = async (action: () => Promise<void>) => {
    if (busy.current) return;
    busy.current = true;
    try {
      await action();
    } finally {
      busy.current = false;
    }
  };

  const recordRelapse = () =>
    run(async () => {
      const key = tapKey.current ?? newTapKey();
      tapKey.current = key;
      const previous = state;
      setState({ phase: 'recording' });
      let entry: RelapseRecorded;
      try {
        entry = await categoriesAPI.recordRelapse(category.id, key);
      } catch {
        setState(previous);
        onError(RECORD_FAILED);
        return;
      }
      tapKey.current = null;
      setState({ phase: 'recorded', entry: landedEntry(previous, entry) });
      await refresh();
    });

  const undo = (entry: RelapseRecorded) =>
    run(async () => {
      setState({ phase: 'undoing', entry });
      try {
        await entriesAPI.delete(entry.id);
      } catch {
        setState({ phase: 'recorded', entry });
        onError(UNDO_FAILED);
        return;
      }
      setState({ phase: 'idle' });
      await refresh();
    });

  const openDetails = (entry: RelapseRecorded) => {
    const stored = amountField && entry.values.find((value) => value.field_id === amountField.id);
    setAmount(stored ? stored.value : '');
    setNote(entry.notes ?? '');
    setState({ phase: 'details', entry });
  };

  const saveDetails = (entry: RelapseRecorded) =>
    run(async () => {
      const payload: Partial<EntryCreate> = {};
      const trimmedNote = note.trim();
      if (trimmedNote !== '') payload.notes = trimmedNote;
      const trimmedAmount = amount.trim();
      if (amountField && trimmedAmount !== '') {
        if (!(Number(trimmedAmount) > 0)) {
          onError(AMOUNT_NOT_POSITIVE);
          return;
        }
        // PATCH replaces the whole value list, so what the server wrote for the
        // tap (the ticked box) goes back along with the amount.
        payload.values = [
          ...entry.values
            .filter((value) => value.field_id !== amountField.id)
            .map((value) => ({ field_id: value.field_id, value: value.value })),
          { field_id: amountField.id, value: trimmedAmount },
        ];
      }
      if (Object.keys(payload).length === 0) {
        setState({ phase: 'recorded', entry });
        return;
      }

      setState({ phase: 'saving-details', entry });
      let updated: Entry;
      try {
        updated = await entriesAPI.update(entry.id, payload);
      } catch {
        setState({ phase: 'details', entry });
        onError(DETAILS_FAILED);
        return;
      }
      setState({ phase: 'recorded', entry: { ...updated, created: entry.created } });
      await refresh();
    });

  const recordedEntry = state.phase === 'idle' || state.phase === 'recording' ? null : state.entry;

  return (
    <div className="relative bg-card border border-white/5 rounded-3xl p-6">
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 mb-2">
            <Flame className="w-4 h-4 shrink-0 text-lime" strokeWidth={2} aria-hidden="true" />
            {/* The link stretches over the whole card (`after:inset-0`), so a tap
                anywhere but on a button opens the history; the buttons sit above
                it on their own layer. */}
            <Link
              href={categoryHref(pathname, category.id)}
              aria-label={`${category.name}: история срывов`}
              className="inline-flex min-w-0 items-center gap-1 text-[13px] font-medium uppercase tracking-widest text-lime after:absolute after:inset-0 after:rounded-3xl focus-visible:outline-none focus-visible:after:ring-2 focus-visible:after:ring-lime"
            >
              <span className="truncate">{category.name}</span>
              <ChevronRight className="w-4 h-4 shrink-0" strokeWidth={2} aria-hidden="true" />
            </Link>
          </div>
          <p className="text-4xl font-bold text-lime tracking-tight tabular-nums">
            {streak ? formatCleanDays(streak.current_streak) : '—'}
          </p>
          {streak && (
            <p className="mt-1 text-xs text-text-secondary">Best {formatDays(streak.best_streak)}</p>
          )}
        </div>

        <div className="relative z-10 flex flex-wrap items-center justify-end gap-2">
          <button type="button" onClick={() => void recordRelapse()} disabled={working} className={BUTTON_CLASS}>
            <AlertCircle className="w-4 h-4" strokeWidth={2} aria-hidden="true" />
            Случилось
          </button>
          {onOpenEntries && (
            <button
              type="button"
              onClick={onOpenEntries}
              className="min-h-11 rounded-full px-3 py-2 text-sm text-text-secondary hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-lime"
            >
              Записи
            </button>
          )}
        </div>
      </div>

      {recordedEntry !== null && state.phase !== 'details' && state.phase !== 'saving-details' && (
        <div className="relative z-10 mt-4 flex flex-wrap items-center gap-2">
          <span role="status" className="basis-full text-sm font-medium text-text-primary sm:basis-auto sm:mr-auto">
            {recordedEntry.created ? 'Срыв записан' : 'Срыв уже записан'}
          </span>
          <button
            type="button"
            onClick={() => openDetails(recordedEntry)}
            disabled={working}
            className={BUTTON_CLASS}
          >
            Подробнее
          </button>
          {recordedEntry.created && (
            <button
              type="button"
              onClick={() => void undo(recordedEntry)}
              disabled={working}
              className={BUTTON_CLASS}
            >
              Отменить
            </button>
          )}
        </div>
      )}

      {recordedEntry !== null && (state.phase === 'details' || state.phase === 'saving-details') && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void saveDetails(recordedEntry);
          }}
          aria-label={`${category.name}: подробности срыва`}
          className="relative z-10 mt-5 space-y-3"
        >
          {amountField && (
            <div>
              <label htmlFor={amountId} className="block text-xs text-text-secondary mb-1">
                {amountField.name}
              </label>
              <FieldValueInput id={amountId} field={amountField} value={amount} onChange={setAmount} />
            </div>
          )}
          <div>
            <label htmlFor={noteId} className="block text-xs text-text-secondary mb-1">
              Заметка
            </label>
            <input
              id={noteId}
              type="text"
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="Что случилось?"
              className={entryInputClass}
            />
          </div>
          <div className="flex items-center gap-3 pt-1">
            <button
              type="submit"
              disabled={working}
              className="min-h-11 px-5 py-2.5 bg-lime text-background rounded-3xl font-medium transition-all duration-200 hover:-translate-y-0.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-lime focus-visible:ring-offset-2 focus-visible:ring-offset-card disabled:opacity-50 disabled:hover:translate-y-0"
            >
              {state.phase === 'saving-details' ? 'Сохранение…' : 'Сохранить'}
            </button>
            <button
              type="button"
              onClick={() => setState({ phase: 'recorded', entry: recordedEntry })}
              disabled={working}
              className="min-h-11 px-5 py-2.5 rounded-3xl font-medium text-text-secondary transition-colors duration-200 hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-lime disabled:opacity-50"
            >
              Отмена
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
