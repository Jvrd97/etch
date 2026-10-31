'use client';
// [review:need-review] PHASE-03/244
// summary: the «Совет» block of the week screen — a button that asks the model for the advice on sleep, sport and supplements, its states (busy, ready, again, «данных мало», refusal), the days the advice covers, and the «не медицинская рекомендация» note that is on screen before anything is asked

import { useHealthAdvice, type HealthAdviceClient } from '@/hooks/useHealthAdvice';
import { shortDate } from '@/lib/week-review';

export const ADVICE_BUTTON = 'Написать совет';
export const ADVICE_BUTTON_BUSY = 'Пишу совет…';
export const ADVICE_BUTTON_AGAIN = 'Написать заново';
export const ADVICE_DISCLAIMER = 'Это не медицинская рекомендация.';
export const NOT_ENOUGH_DATA_TEXT =
  'Данных мало: совет появится, когда накопится хотя бы несколько дней шагов, тренировок, пульса или приёма добавок.';

export interface HealthAdviceBlockProps {
  /** Replaces the network client in tests. */
  client?: HealthAdviceClient;
}

export default function HealthAdviceBlock({ client }: HealthAdviceBlockProps) {
  const { state, write } = useHealthAdvice(client);
  const busy = state.status === 'loading';

  return (
    <section aria-label="Совет" aria-live="polite" className="space-y-3">
      <h2 className="text-xl font-semibold text-text-primary">Совет</h2>
      <p className="text-sm text-text-secondary">
        Сон, спорт и добавки за последние 7 дней против 7 дней до них.
      </p>
      <p className="text-sm font-medium text-text-primary">{ADVICE_DISCLAIMER}</p>
      {state.status === 'ready' && (
        <div className="bg-card border border-white/5 rounded-3xl p-5">
          <p className="whitespace-pre-wrap break-words text-text-primary">{state.advice.text}</p>
          <p className="mt-3 text-xs text-text-disabled">
            За {shortDate(state.advice.starts_on)} — {shortDate(state.advice.ends_on)} (
            {state.advice.days} дн.). Текст написан моделью по цифрам и не сохраняется.
          </p>
        </div>
      )}
      {state.status === 'not_enough_data' && (
        <p className="text-sm text-text-secondary">{NOT_ENOUGH_DATA_TEXT}</p>
      )}
      {state.status === 'error' && (
        <p role="alert" className="text-sm text-danger">
          {state.message}
        </p>
      )}
      <button
        type="button"
        onClick={write}
        disabled={busy}
        className="min-h-11 rounded-full bg-lime px-5 text-sm font-semibold text-black disabled:opacity-40"
      >
        {busy ? ADVICE_BUTTON_BUSY : state.status === 'ready' ? ADVICE_BUTTON_AGAIN : ADVICE_BUTTON}
      </button>
    </section>
  );
}
