'use client';
// [review:need-review] PHASE-03/129
// summary: one proposal on Today — the rule spelled as a sentence rather than shown as JSON, the window in dates, who proposed it, and the two buttons that are the only way it becomes an obligation or stops existing

import type { Category, Challenge } from '@/lib/api';
import { describeRule, describeWindow } from '@/lib/challenges';

export const ACCEPT_LABEL = 'Принять';
export const DECLINE_LABEL = 'Отклонить';

/** Кто предложил, словами. Человека здесь не бывает: он не предлагает, а заводит. */
export const ORIGIN_LABELS: Record<Challenge['origin'], string> = {
  ai: 'предложил разбор дня',
  plan: 'предложил план дня',
  human: 'предложено вручную',
};

/**
 * Сказано под кнопками, потому что «принять» — это про прошлое тоже.
 *
 * Окно предложения могло начаться вчера. Человек, нажимающий «принять», должен
 * знать, что прожитые дни посчитаются по правилу сразу, а не начнут считаться
 * с завтра.
 */
export const ACCEPT_HINT =
  'Дни считаются с начала окна, включая прожитые: обязательство начинается там, ' +
  'где написано, а не в момент согласия.';

export interface ProposedChallengeCardProps {
  challenge: Challenge;
  /** Categories the Today screen already loaded; the rule points into one. */
  categories: Category[];
  onAccept: (challenge: Challenge) => void;
  onDecline: (challenge: Challenge) => void;
  /** True while the answer to this proposal is in flight. */
  answering?: boolean;
}

/**
 * Предложение, которое ещё не обязательство.
 *
 * Своя карточка, а не приглушённый `ChallengeCard`: у предложения нет ни счёта,
 * ни сегодняшнего дня, ни кнопки «засчитать», — печатать «день 0 из 14,
 * промахов 0» значило бы показывать счёт того, что не считается.
 */
export default function ProposedChallengeCard({
  challenge,
  categories,
  onAccept,
  onDecline,
  answering = false,
}: ProposedChallengeCardProps) {
  return (
    <article className="rounded-3xl border border-lime/30 bg-card p-4 space-y-2">
      <h3 className="text-sm font-medium text-text-primary">{challenge.title}</h3>

      <p className="text-sm text-text-secondary">
        {describeRule(challenge, categories)}
      </p>
      <p className="text-xs text-text-secondary">
        {describeWindow(challenge)} · {ORIGIN_LABELS[challenge.origin]}
      </p>

      <div className="flex gap-3 pt-1">
        <button
          type="button"
          disabled={answering}
          onClick={() => onAccept(challenge)}
          className="px-4 py-2 rounded-2xl bg-lime text-black text-sm font-medium disabled:opacity-60"
        >
          {ACCEPT_LABEL}
        </button>
        <button
          type="button"
          disabled={answering}
          onClick={() => onDecline(challenge)}
          className="px-4 py-2 rounded-2xl border border-white/10 text-sm text-text-secondary disabled:opacity-60"
        >
          {DECLINE_LABEL}
        </button>
      </div>

      <p className="text-xs text-text-secondary">{ACCEPT_HINT}</p>
    </article>
  );
}
