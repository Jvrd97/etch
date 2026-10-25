'use client';
// [review:need-review] PHASE-01/206
// summary: the list of a quick-mark card's day — every tap its own row with its time and amount, the day's total as the card prints it, a taken-back set kept and marked, the undo offered only where the server says it will be taken, and its refusal shown in the list

import { useId, useState } from 'react';
import type { QuickMark } from '@/lib/api';
import { useQuickMarkDayEvents } from '@/hooks/useQuickMarkDayEvents';
import { markCaption } from '@/lib/quick-marks';
import { daySetsHeading, setAmount } from '@/lib/quick-mark-sets';
import { clockTime } from '@/lib/today-entries';
import { TAP_TARGET_PX } from '@/lib/ui-constants';

interface QuickMarkDaySetsProps {
  /** The card the list was opened from; its category decides which sets are read. */
  mark: QuickMark;
  /**
   * Take one tap back. Resolves with the server's refusal sentence, or null
   * once the tap is undone — the screen owns the totals, so it owns the call.
   */
  onUndo: (eventId: number) => Promise<string | null>;
}

/**
 * The sets of today behind one quick-mark card.
 *
 * Built for the person who did twenty sets of push-ups and wants to see them:
 * each tap is a row with the time it was made and what it was worth, because
 * the day's entry only keeps the sum. The undo sits on the one row the server
 * will accept it for (the last open tap of a button), so the list never offers
 * a button that answers 409 — a person unwinds the day from the bottom up.
 *
 * A set that was taken back stays in the list, struck through, and is not
 * counted: without it the total would fall with nothing on screen to explain
 * why.
 */
export default function QuickMarkDaySets({ mark, onUndo }: QuickMarkDaySetsProps) {
  const headingId = useId();
  const { state, reload } = useQuickMarkDayEvents(mark.category_id);
  const [undoing, setUndoing] = useState<number | null>(null);
  const [refusal, setRefusal] = useState<string | null>(null);

  const total = markCaption(mark);
  const events = state.status === 'ready' ? state.events : [];
  // A category can carry several buttons (+250 and +500); the rows then say
  // which one each came from, and stay quiet when there is only one to name.
  const namesButtons = new Set(events.map((event) => event.quick_mark_id)).size > 1;

  const handleUndo = async (eventId: number) => {
    setUndoing(eventId);
    setRefusal(null);
    const refused = await onUndo(eventId);
    setRefusal(refused);
    // Read again after a refusal as well: a 409 means the journal is not what
    // the list was drawn from, and the fresh rows are the explanation.
    reload();
    setUndoing(null);
  };

  return (
    <section aria-labelledby={headingId} className="space-y-3">
      <div className="flex items-baseline justify-between gap-3">
        <h3 id={headingId} className="text-sm font-medium text-text-primary">
          {daySetsHeading(mark)}
        </h3>
        {total && (
          <p className="text-sm tabular-nums text-text-secondary">Итого за день: {total}</p>
        )}
      </div>

      {refusal && (
        <p role="alert" className="text-sm text-danger break-words">
          {refusal}
        </p>
      )}

      {state.status === 'loading' && (
        <p role="status" className="text-sm text-text-secondary">
          Загружаю подходы…
        </p>
      )}

      {state.status === 'failed' && (
        <div className="flex flex-wrap items-center gap-3">
          <p role="alert" className="text-sm text-danger break-words">
            {state.message}
          </p>
          <button
            type="button"
            onClick={reload}
            style={{ minHeight: TAP_TARGET_PX }}
            className="rounded-2xl border border-white/10 px-4 text-sm font-medium text-lime"
          >
            Повторить
          </button>
        </div>
      )}

      {state.status === 'ready' &&
        (events.length === 0 ? (
          <p className="text-sm text-text-secondary">За сегодня пока ничего не отмечено.</p>
        ) : (
          <ul
            aria-label={daySetsHeading(mark)}
            className="divide-y divide-white/5 border-y border-white/5"
          >
            {events.map((event) => {
              const taken = event.undone_at !== null;
              const time = clockTime(event.occurred_at);
              const amount = setAmount(event);
              return (
                // Every row is as tall as the undo button, so the rows do not
                // jump when the button moves to the previous set after an undo.
                <li
                  key={event.event_id}
                  style={{ minHeight: TAP_TARGET_PX }}
                  className="flex items-center gap-3"
                >
                  <time className="shrink-0 text-sm tabular-nums text-text-secondary">
                    {time}
                  </time>
                  <span
                    className={`min-w-0 flex-1 truncate text-sm ${
                      taken ? 'text-text-secondary line-through' : 'text-text-primary'
                    }`}
                  >
                    {amount}
                    {namesButtons && (
                      <span className="ml-2 text-text-secondary no-underline">{event.label}</span>
                    )}
                  </span>
                  {taken && <span className="shrink-0 text-xs text-text-secondary">отменён</span>}
                  {event.undoable && (
                    <button
                      type="button"
                      onClick={() => void handleUndo(event.event_id)}
                      disabled={undoing !== null}
                      aria-label={`Отменить: ${amount} в ${time}`}
                      style={{ minHeight: TAP_TARGET_PX }}
                      className="shrink-0 rounded-xl px-3 text-sm text-text-secondary hover:text-text-primary disabled:opacity-50"
                    >
                      Отменить
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        ))}
    </section>
  );
}
