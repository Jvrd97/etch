'use client';
// [review:need-review] PHASE-03/160
// summary: one interval corrected where it is drawn — its two ends as wall clock, the task it belongs to, a note, and a patch that carries only what actually changed so «не трогай задачу» stays different from «убери задачу»

import { useState } from 'react';
import { Check, X } from 'lucide-react';
import type { ActivityInterval, ActivityIntervalPatch } from '@/lib/api';
import { clock } from '@/lib/time';

export const SAVE_LABEL = 'Сохранить';
export const CANCEL_LABEL = 'Отменить';

export interface IntervalEditorProps {
  interval: ActivityInterval;
  /** True while a request for this interval is in flight; the fields lock. */
  saving: boolean;
  onSave: (patch: ActivityIntervalPatch) => void;
  onCancel: () => void;
}

/**
 * A wall-clock time put back onto the date the interval already has.
 *
 * The date never changes here: moving an interval to another day is not a
 * correction of its ends, it is a different record, and letting a typo in a
 * time field move an hour into yesterday would be the worst kind of silent.
 */
export function withClock(moment: string, wallClock: string): string | null {
  const match = /^(\d{1,2}):(\d{2})$/.exec(wallClock.trim());
  if (!match) return null;
  const hours = Number(match[1]);
  const minutes = Number(match[2]);
  if (hours > 23 || minutes > 59) return null;
  const at = new Date(moment);
  at.setHours(hours, minutes, 0, 0);
  return at.toISOString();
}

/**
 * Only what actually changed, so the server is never told to keep what it has.
 *
 * `null` for a task means «убрать привязку» and an absent key means «не трогать
 * её»; merging the two would unlink a task on every corrected note.
 */
export function changedFields(
  interval: ActivityInterval,
  draft: { from: string; to: string; task: string; note: string }
): ActivityIntervalPatch {
  const patch: ActivityIntervalPatch = {};

  const started = withClock(interval.started_at, draft.from);
  if (started !== null && draft.from !== clock(interval.started_at)) {
    patch.started_at = started;
  }
  const ended = withClock(interval.ended_at, draft.to);
  if (ended !== null && draft.to !== clock(interval.ended_at)) {
    patch.ended_at = ended;
  }

  const currentTask =
    interval.plan_task_id === null ? '' : String(interval.plan_task_id);
  if (draft.task !== currentTask) {
    patch.plan_task_id = draft.task.trim() === '' ? null : Number(draft.task);
  }

  const currentNote = interval.note ?? '';
  if (draft.note !== currentNote) {
    patch.note = draft.note.trim() === '' ? null : draft.note.trim();
  }

  return patch;
}

/**
 * The editor of one interval, opened in place of the row it edits.
 *
 * In place rather than in a dialogue, for the same reason the plan's line editor
 * is: the tape is read as a whole — this hour next to the one above it — and a
 * modal takes that away at the moment it is needed most.
 */
export default function IntervalEditor({
  interval,
  saving,
  onSave,
  onCancel,
}: IntervalEditorProps) {
  const [from, setFrom] = useState(() => clock(interval.started_at));
  const [to, setTo] = useState(() => clock(interval.ended_at));
  const [task, setTask] = useState(
    interval.plan_task_id === null ? '' : String(interval.plan_task_id)
  );
  const [note, setNote] = useState(interval.note ?? '');

  // Правка соседа переставляет ленту, и под тем же экраном оказывается уже
  // другой интервал; поля обязаны последовать за ним, иначе человек сохранит
  // поверх чужого часа то, что набирал в своём. Сброс идёт прямо в рендере, а
  // не эффектом: эффект сначала показал бы кадр со старыми полями и только
  // потом перерисовал его новыми.
  const [shown, setShown] = useState(interval);
  if (shown !== interval) {
    setShown(interval);
    setFrom(clock(interval.started_at));
    setTo(clock(interval.ended_at));
    setTask(interval.plan_task_id === null ? '' : String(interval.plan_task_id));
    setNote(interval.note ?? '');
  }

  const field =
    'w-full rounded-2xl bg-surface border border-white/10 px-3 py-2 text-sm text-text-primary';

  return (
    <div className="mt-2 space-y-2" data-testid={`interval-editor-${interval.id}`}>
      <div className="flex flex-wrap gap-2">
        <label className="flex-1 min-w-[6rem]">
          <span className="text-xs text-text-disabled">Начало</span>
          <input
            className={field}
            value={from}
            disabled={saving}
            onChange={(event) => setFrom(event.target.value)}
            aria-label="Начало интервала"
          />
        </label>
        <label className="flex-1 min-w-[6rem]">
          <span className="text-xs text-text-disabled">Конец</span>
          <input
            className={field}
            value={to}
            disabled={saving}
            onChange={(event) => setTo(event.target.value)}
            aria-label="Конец интервала"
          />
        </label>
        <label className="flex-1 min-w-[6rem]">
          <span className="text-xs text-text-disabled">Задача</span>
          <input
            className={field}
            value={task}
            disabled={saving}
            inputMode="numeric"
            onChange={(event) => setTask(event.target.value)}
            aria-label="Задача интервала"
          />
        </label>
      </div>

      <label className="block">
        <span className="text-xs text-text-disabled">Заметка</span>
        <input
          className={field}
          value={note}
          disabled={saving}
          onChange={(event) => setNote(event.target.value)}
          aria-label="Заметка интервала"
        />
      </label>

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={saving}
          onClick={() => onSave(changedFields(interval, { from, to, task, note }))}
          className="inline-flex items-center gap-1 rounded-2xl bg-lime px-3 py-1.5 text-sm text-black disabled:opacity-50"
        >
          <Check className="w-4 h-4" strokeWidth={2} />
          {SAVE_LABEL}
        </button>
        <button
          type="button"
          disabled={saving}
          onClick={onCancel}
          className="inline-flex items-center gap-1 rounded-2xl bg-surface px-3 py-1.5 text-sm text-text-secondary"
        >
          <X className="w-4 h-4" strokeWidth={2} />
          {CANCEL_LABEL}
        </button>
      </div>
    </div>
  );
}
