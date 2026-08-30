'use client';
// [review:need-review] PHASE-03/90
// summary: the итог of a day on screen — the verdict, the condition it failed on and which anchor was missed, the counters and the streak, what could not be measured, the prose of a closed day, the form that closes an unclosed one, and the override that stays dead until a note is written and is never offered on a day whose verdict arrived as prose

import { useState } from 'react';
import Markdown from '@/components/Markdown';
import type { DayCloseDraft, DaySummary } from '@/lib/api';
import {
  formatMinutes,
  missingDataLabel,
  streakLabel,
  verdictLabel,
  verdictReasonLabel,
} from '@/lib/day-format';

/** The heading of the block. */
export const VERDICT_TITLE = 'Итог дня';

export const CLOSE_DAY = 'Закрыть день';
export const CLOSE_FAILED = 'День не закрылся';

/** Said above the reason, so the number is never left to speak for itself. */
export const REASON_PREFIX = 'Не выполнено:';
export const MISSING_ANCHORS_TITLE = 'Не отмечены якоря';

export const BODY_LABEL = 'Что случилось вместо плана, что мешало';
export const BODY_PLACEHOLDER =
  'Например: два часа ушли на созвон, который был письмом';
export const WORK_MINUTES_LABEL = 'Минут работы';
export const WORK_MINUTES_PLACEHOLDER = 'не измерено';
export const PROSE_TITLE = 'Как прошло';

export const OVERRIDE_TITLE = 'Переопределить вердикт';
export const OVERRIDE_NOTE_LABEL = 'Почему день всё-таки выигран';
export const OVERRIDE_NOTE_PLACEHOLDER =
  'Например: задача сделана, отметить забыл';
export const OVERRIDE_SAVE = 'Записать «выигран»';
export const OVERRIDE_MADE = 'Вердикт переопределён вручную:';
export const IMPORTED_VERDICT =
  'Вердикт пришёл прозой из personal-os — его не пересчитывают. ' +
  'Правится в summaries/ и импортируется заново.';

export interface DayVerdictProps {
  summary: DaySummary;
  /** Closes the day; resolves once the server has judged it. */
  onClose: (draft: DayCloseDraft) => Promise<void>;
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
 *
 * **Каждая кнопка шлёт только то, что человек здесь набрал.** `POST /close`
 * writes the fields it is given and leaves the rest of the row alone, so the
 * override sends two fields and the prose of a day the agent closed through the
 * CLI survives the click. Sending the whole итог back — the shape this block
 * used to imply — would mean the screen is responsible for keeping columns it
 * never showed.
 *
 * **День, чей вердикт пришёл прозой, здесь не переопределяется.** A row with
 * `source: 'import'` arrives with `closed: true`, so it would otherwise land in
 * the override branch; the server answers 409 to that write, and this block says
 * so instead of offering a button that cannot work.
 */
export default function DayVerdict({ summary, onClose }: DayVerdictProps) {
  const [note, setNote] = useState('');
  const [body, setBody] = useState('');
  const [workMinutes, setWorkMinutes] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (draft: DayCloseDraft) => {
    setBusy(true);
    setError(null);
    try {
      await onClose(draft);
    } catch (err) {
      setError(err instanceof Error ? err.message : CLOSE_FAILED);
    } finally {
      setBusy(false);
    }
  };

  const reason = verdictReasonLabel(summary.verdict_reason);
  const showReason = summary.closed && reason !== '';
  const imported = summary.source === 'import';

  // Only the fields a person filled in travel: an empty box is «не сказал»,
  // and the server distinguishes that from a null it was handed.
  const closingDraft = (): DayCloseDraft => {
    const draft: DayCloseDraft = {};
    if (body.trim() !== '') draft.body_md = body.trim();
    if (workMinutes.trim() !== '') draft.work_minutes = Number(workMinutes);
    return draft;
  };

  return (
    <section className="bg-card border border-white/5 rounded-3xl p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="text-xl font-semibold text-text-primary">
          {verdictLabel(summary.verdict)}
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

      {summary.body_md !== '' && (
        <div className="mt-5 pt-5 border-t border-white/5">
          <p className="text-sm text-text-secondary">{PROSE_TITLE}</p>
          <div className="mt-2 text-text-primary space-y-2">
            <Markdown content={summary.body_md} />
          </div>
        </div>
      )}

      {summary.verdict_override && summary.verdict_override_note !== null && (
        <p className="mt-5 pt-5 border-t border-white/5 text-sm text-text-secondary">
          {OVERRIDE_MADE} {summary.verdict_override_note}
        </p>
      )}

      {!summary.closed ? (
        <div className="mt-5 pt-5 border-t border-white/5">
          <textarea
            rows={3}
            value={body}
            aria-label={BODY_LABEL}
            placeholder={BODY_PLACEHOLDER}
            onChange={(event) => setBody(event.target.value)}
            className="w-full bg-surface rounded-2xl px-4 py-2 text-text-primary placeholder:text-text-disabled"
          />
          <input
            type="number"
            min={0}
            value={workMinutes}
            aria-label={WORK_MINUTES_LABEL}
            placeholder={WORK_MINUTES_PLACEHOLDER}
            onChange={(event) => setWorkMinutes(event.target.value)}
            className="mt-3 w-full bg-surface rounded-2xl px-4 py-2 text-text-primary placeholder:text-text-disabled"
          />
          <button
            type="button"
            disabled={busy}
            onClick={() => void run(closingDraft())}
            className="mt-3 rounded-2xl bg-surface px-4 py-2 text-text-primary disabled:opacity-50"
          >
            {CLOSE_DAY}
          </button>
        </div>
      ) : imported ? (
        <p className="mt-5 pt-5 border-t border-white/5 text-sm text-text-secondary">
          {IMPORTED_VERDICT}
        </p>
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
                void run({
                  verdict_override: true,
                  verdict_override_note: note.trim(),
                })
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
