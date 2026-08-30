'use client';
// [review:need-review] PHASE-03/88
// summary: the mark control of one plan line — a box that cycles пусто → ✓ → ✕ → пусто on click, «стало неактуально» as a separate deliberate button, and the «как прошло» note that appears once there is a mark

import { useEffect, useState } from 'react';
import type { MarkState } from '@/lib/api';
import { MARK_GLYPH, MARK_LABEL, MARK_PENDING_LABEL } from '@/lib/marks';

/** Placeholder of the note field; it is the question the note answers. */
export const NOTE_PLACEHOLDER = 'Как прошло';

/** The label of the button that sets a line aside. */
export const SKIP_LABEL = 'неактуально';

export interface PlanItemMarkProps {
  itemId: string;
  state: MarkState | null;
  note: string;
  saving?: boolean;
  /** One click on the box: пусто → done → failed → пусто. */
  onCycle: (itemId: string) => void;
  /** Sets a state directly; `skipped` is only reachable this way. */
  onSetState: (itemId: string, state: MarkState | null) => void;
  /** Writes the note; only called for a line that already has a mark. */
  onSetNote: (itemId: string, note: string) => void;
  compact?: boolean;
}

/**
 * The tick of one line, and the sentence next to it.
 *
 * The box is one control walking one ring rather than three buttons: marking a
 * day is done fast, with a finger, on the way to something else, and the whole
 * reason `plan_server.py` earned this rewrite is that its marks were positional
 * and lost. `skipped` sits outside the ring on purpose — "стало неактуально" is
 * a judgement about the plan and has to be chosen, not walked into.
 *
 * The note appears only once there is a mark: the note lives on the mark row,
 * and a field with nowhere to save to is a field that loses what is typed in it.
 */
export default function PlanItemMark({
  itemId,
  state,
  note,
  saving = false,
  onCycle,
  onSetState,
  onSetNote,
  compact = false,
}: PlanItemMarkProps) {
  const [draft, setDraft] = useState(note);

  // The note is edited locally and committed on blur; a re-read of the day (or
  // another tab's write) replaces the draft when the stored note changes.
  useEffect(() => {
    setDraft(note);
  }, [note]);

  const glyph = state === null ? '' : MARK_GLYPH[state];
  const label = state === null ? MARK_PENDING_LABEL : MARK_LABEL[state];
  const tone =
    state === 'done'
      ? 'border-lime text-lime'
      : state === 'failed'
        ? 'border-warning text-warning'
        : state === 'skipped'
          ? 'border-white/10 text-text-disabled'
          : 'border-white/10 text-text-disabled';

  return (
    <div className="flex items-start gap-2">
      <button
        type="button"
        aria-label={label}
        aria-pressed={state !== null}
        disabled={saving}
        onClick={() => onCycle(itemId)}
        className={`shrink-0 rounded-2xl border ${tone} ${
          compact ? 'w-7 h-7 text-sm' : 'w-8 h-8'
        } flex items-center justify-center disabled:opacity-50`}
      >
        {glyph}
      </button>

      <div className="min-w-0 flex-1">
        {state !== null && (
          <input
            type="text"
            value={draft}
            aria-label={NOTE_PLACEHOLDER}
            placeholder={NOTE_PLACEHOLDER}
            onChange={(event) => setDraft(event.target.value)}
            onBlur={() => {
              if (draft !== note) onSetNote(itemId, draft);
            }}
            className={`w-full bg-surface rounded-2xl px-3 py-1.5 text-text-primary placeholder:text-text-disabled ${
              compact ? 'text-sm' : ''
            }`}
          />
        )}
      </div>

      <button
        type="button"
        disabled={saving}
        onClick={() =>
          onSetState(itemId, state === 'skipped' ? null : 'skipped')
        }
        className={`shrink-0 rounded-2xl px-2 py-1 text-xs ${
          state === 'skipped'
            ? 'bg-surface text-text-secondary'
            : 'text-text-disabled'
        } disabled:opacity-50`}
      >
        {SKIP_LABEL}
      </button>
    </div>
  );
}
