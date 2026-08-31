'use client';
// [review:need-review] PHASE-03/92
// summary: the anchors of a day as their own block — one row per kind of the catalogue, `relationship` among them and marked the same way, a box that cycles пусто → ✓ → ✕ → пусто, «неактуально» as a deliberate separate button, and the anchors the day has not closed named rather than counted

import { useState } from 'react';
import type { AnchorState, DayAnchor, DayAnchors as DayAnchorsPayload } from '@/lib/api';
import {
  MARK_GLYPH,
  MARK_LABEL,
  MARK_PENDING_LABEL,
  nextMarkState,
} from '@/lib/marks';

export const ANCHORS_TITLE = 'Якоря дня';
export const ANCHORS_EMPTY = 'Канон этого дня не называет ни одного якоря';
export const ANCHORS_MISSING_TITLE = 'Не закрыты';
export const ANCHORS_FAILED = 'Якорь не отметился';
export const SKIP_LABEL = 'неактуально';
export const NOT_IN_CANON = 'не в каноне этого дня';

// The ring one click walks is `lib/marks.ts`'s, not a copy of it: an anchor is
// ticked with a finger on the way past, and a control that behaved differently
// from the mark box directly above it would be worse than a second control.

export interface DayAnchorsProps {
  payload: DayAnchorsPayload;
  /** Writes one anchor; resolves once the server has stored it. */
  onMark: (kind: string, state: AnchorState | null) => Promise<void>;
  compact?: boolean;
}

/**
 * The anchors of one day, as a block a person can act on.
 *
 * Until `#92` an anchor was a bullet recognised by the substring «якор», so a
 * plan that worded one differently lost it in silence and a day without a plan
 * had no anchors at all. Here every kind of the catalogue has a row of its own,
 * answered or not — and `relationship`, «вечер с близкими», sits in that list
 * beside the anchors of health rather than being the priority nobody could
 * tick.
 *
 * A kind the canon of *this* day does not name is shown and marked, but said to
 * be outside the canon: the day of 14 August is judged by five anchors, and
 * hiding the sixth would make the screen disagree with the verdict beside it.
 */
export default function DayAnchors({
  payload,
  onMark,
  compact = false,
}: DayAnchorsProps) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async (kind: string, state: AnchorState | null) => {
    setBusy(kind);
    setError(null);
    try {
      await onMark(kind, state);
    } catch (err) {
      setError(err instanceof Error ? err.message : ANCHORS_FAILED);
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="bg-card border border-white/5 rounded-3xl p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="text-xl font-semibold text-text-primary">
          {ANCHORS_TITLE}
        </h2>
        <span className="text-text-secondary">
          {payload.done} из {payload.total}
        </span>
      </div>

      {error !== null && (
        <p className="mt-3 text-sm text-warning">{error}</p>
      )}

      {payload.anchors.length === 0 ? (
        <p className="mt-4 text-text-secondary">{ANCHORS_EMPTY}</p>
      ) : (
        <ul className="mt-4 space-y-2">
          {payload.anchors.map((anchor) => (
            <AnchorRow
              key={anchor.kind}
              anchor={anchor}
              busy={busy === anchor.kind}
              compact={compact}
              onMark={run}
            />
          ))}
        </ul>
      )}

      {payload.missing.length > 0 && (
        <div className="mt-5 pt-5 border-t border-white/5">
          <p className="text-sm text-text-secondary">{ANCHORS_MISSING_TITLE}</p>
          <ul className="mt-2 space-y-1">
            {payload.missing.map((title) => (
              <li key={title} className="text-text-primary">
                {title}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

interface AnchorRowProps {
  anchor: DayAnchor;
  busy: boolean;
  compact: boolean;
  onMark: (kind: string, state: AnchorState | null) => Promise<void>;
}

function AnchorRow({ anchor, busy, compact, onMark }: AnchorRowProps) {
  const glyph = anchor.state === null ? '' : MARK_GLYPH[anchor.state];
  const label =
    anchor.state === null ? MARK_PENDING_LABEL : MARK_LABEL[anchor.state];
  const tone =
    anchor.state === 'done'
      ? 'border-lime text-lime'
      : anchor.state === 'failed'
        ? 'border-warning text-warning'
        : 'border-white/10 text-text-disabled';

  return (
    <li className="flex items-center gap-3">
      <button
        type="button"
        aria-label={`${anchor.title}: ${label}`}
        aria-pressed={anchor.state !== null}
        disabled={busy}
        onClick={() => void onMark(anchor.kind, nextMarkState(anchor.state))}
        className={`shrink-0 rounded-2xl border ${tone} ${
          compact ? 'w-7 h-7 text-sm' : 'w-8 h-8'
        } flex items-center justify-center disabled:opacity-50`}
      >
        {glyph}
      </button>
      <span className="text-text-primary">{anchor.title}</span>
      {!anchor.required_today && (
        <span className="text-xs text-text-disabled">{NOT_IN_CANON}</span>
      )}
      <button
        type="button"
        disabled={busy}
        onClick={() => void onMark(anchor.kind, 'skipped')}
        className="ml-auto text-sm text-text-disabled hover:text-text-secondary disabled:opacity-50"
      >
        {SKIP_LABEL}
      </button>
    </li>
  );
}
