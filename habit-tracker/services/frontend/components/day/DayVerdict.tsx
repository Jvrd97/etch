'use client';
// [review:need-review] PHASE-03/90, PHASE-03/143
// summary: the итог of a day on screen — the verdict, the condition it failed on and which anchor was missed, the counters and the streak, what could not be measured, the two buttons closing takes — ревью 15:40 и вечернее закрытие — with the stage saying «вердикт будет вечером» instead of «проиграл», the note a day closed in one touch carries, and the override that stays dead until a note is written

import { useState } from 'react';
import type { DayCloseDraft, DayReviewDraft, DaySummary } from '@/lib/api';
import {
  REVIEW_SKIPPED,
  closingHeadline,
  formatMinutes,
  missingDataLabel,
  streakLabel,
  verdictReasonLabel,
} from '@/lib/day-format';

/** The heading of the block. */
export const VERDICT_TITLE = 'Итог дня';

export const CLOSE_DAY = 'Закрыть день';
export const CLOSE_FAILED = 'День не закрылся';

/** Касание около 15:40 — рабочая часть закрытия, без вердикта. */
export const REVIEW_DAY = 'Записать ревью 15:40';
export const REVIEW_DONE = 'Обновить ревью';
export { REVIEW_SKIPPED };

/** Said above the reason, so the number is never left to speak for itself. */
export const REASON_PREFIX = 'Не выполнено:';
export const MISSING_ANCHORS_TITLE = 'Не отмечены якоря';

export const OVERRIDE_TITLE = 'Переопределить вердикт';
export const OVERRIDE_NOTE_LABEL = 'Почему день всё-таки выигран';
export const OVERRIDE_NOTE_PLACEHOLDER =
  'Например: задача сделана, отметить забыл';
export const OVERRIDE_SAVE = 'Записать «выигран»';
export const OVERRIDE_MADE = 'Вердикт переопределён вручную:';

export interface DayVerdictProps {
  summary: DaySummary;
  /** Closes the day; resolves once the server has judged it. */
  onClose: (draft: DayCloseDraft) => Promise<void>;
  /** Записывает касание 15:40; вердикта после него ещё нет. */
  onReview: (draft: DayReviewDraft) => Promise<void>;
}

/**
 * The итог of one day: whether it was won, and what that stands on.
 *
 * Two things this block refuses to do. It never says only «день не выигран» —
 * the condition that failed is named, and when it is the anchors, the lines
 * themselves are listed, because «якоря 4/5» sends nobody anywhere. And it
 * never renders an unclosed day as a loss: `verdict: null` gets the button that
 * closes the day, not a verdict.
 *
 * The override is a visible act rather than a silent edit. Человек имеет право
 * сказать «день был выигран, просто я не отметил» — но с запиской, and the
 * button stays dead until one is typed. The machine's reason stays on screen
 * afterwards: a person re-reading this in a month has to see what was
 * disagreed with.
 */
export default function DayVerdict({
  summary,
  onClose,
  onReview,
}: DayVerdictProps) {
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /** One guard for both touches: the button that is pressed says what to send. */
  const run = async (send: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await send();
    } catch (err) {
      setError(err instanceof Error ? err.message : CLOSE_FAILED);
    } finally {
      setBusy(false);
    }
  };

  const reason = verdictReasonLabel(summary.verdict_reason);
  const showReason = summary.closed && reason !== '';
  const reviewed = summary.reviewed_at !== null;

  return (
    <section className="bg-card border border-white/5 rounded-3xl p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="text-xl font-semibold text-text-primary">
          {closingHeadline(summary.stage, summary.verdict)}
        </h2>
        {summary.streak_after !== null && (
          <span className="text-text-secondary">
            Стрик: {streakLabel(summary.streak_after)}
          </span>
        )}
      </div>

      {showReason && (
        <p className="mt-2 text-text-primary">
          {REASON_PREFIX} <span className="text-lime">{reason}</span>
        </p>
      )}

      <dl className="mt-5 grid gap-x-8 gap-y-3 sm:grid-cols-2">
        <div className="flex justify-between gap-4">
          <dt className="text-text-secondary">Задачи</dt>
          <dd className="text-text-primary">
            {summary.tasks_done} из {summary.tasks_total}
          </dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-text-secondary">Якоря</dt>
          <dd className="text-text-primary">
            {summary.anchors_done} из {summary.anchors_total}
          </dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-text-secondary">Работа</dt>
          <dd className="text-text-primary">
            {summary.work_minutes === null
              ? '—'
              : formatMinutes(summary.work_minutes)}
          </dd>
        </div>
      </dl>

      {summary.missing_data.length > 0 && (
        <ul className="mt-4 flex flex-wrap gap-2">
          {summary.missing_data.map((code) => (
            <li
              key={code}
              className="px-3 py-1 rounded-2xl bg-surface text-sm text-text-secondary"
            >
              {missingDataLabel(code)}
            </li>
          ))}
        </ul>
      )}

      {summary.missing_anchors.length > 0 && (
        <div className="mt-5">
          <p className="text-sm text-text-secondary">{MISSING_ANCHORS_TITLE}</p>
          <ul className="mt-2 space-y-1">
            {summary.missing_anchors.map((text) => (
              <li key={text} className="text-text-primary">
                {text}
              </li>
            ))}
          </ul>
        </div>
      )}

      {summary.verdict_override && summary.verdict_override_note !== null && (
        <p className="mt-5 pt-5 border-t border-white/5 text-sm text-text-secondary">
          {OVERRIDE_MADE} {summary.verdict_override_note}
        </p>
      )}

      {summary.review_skipped && (
        <p className="mt-4 text-sm text-text-secondary">{REVIEW_SKIPPED}</p>
      )}

      {!summary.closed ? (
        <div className="mt-5 flex flex-wrap gap-3">
          <button
            type="button"
            disabled={busy}
            onClick={() => void run(() => onReview({}))}
            className="rounded-2xl bg-surface px-4 py-2 text-text-primary disabled:opacity-50"
          >
            {reviewed ? REVIEW_DONE : REVIEW_DAY}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => void run(() => onClose({}))}
            className="rounded-2xl bg-surface px-4 py-2 text-text-primary disabled:opacity-50"
          >
            {CLOSE_DAY}
          </button>
        </div>
      ) : (
        !summary.verdict_override && (
          <div className="mt-5 pt-5 border-t border-white/5">
            <p className="text-sm text-text-secondary">{OVERRIDE_TITLE}</p>
            <input
              type="text"
              value={note}
              aria-label={OVERRIDE_NOTE_LABEL}
              placeholder={OVERRIDE_NOTE_PLACEHOLDER}
              onChange={(event) => setNote(event.target.value)}
              className="mt-2 w-full bg-surface rounded-2xl px-4 py-2 text-text-primary placeholder:text-text-disabled"
            />
            <button
              type="button"
              disabled={busy || note.trim() === ''}
              onClick={() =>
                void run(() =>
                  onClose({
                    verdict_override: true,
                    verdict_override_note: note.trim(),
                  })
                )
              }
              className="mt-3 rounded-2xl bg-surface px-4 py-2 text-text-primary disabled:opacity-50"
            >
              {OVERRIDE_SAVE}
            </button>
          </div>
        )
      )}

      {error && <p className="mt-3 text-sm text-warning">{error}</p>}
    </section>
  );
}
