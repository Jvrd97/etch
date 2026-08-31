'use client';
// [review:need-review] PHASE-03/127, PHASE-03/128
// summary: the Today card of one obligation — «день N из M, промахов K из N», the state of today's day, how the challenge ended, and the one button that counts a day by hand; every number comes from the server response rather than being recounted here

import { Flag } from 'lucide-react';
import type { Challenge } from '@/lib/api';
import {
  canCountToday,
  formatMisses,
  formatProgress,
  formatStatus,
  formatToday,
} from '@/lib/challenges';

interface ChallengeCardProps {
  challenge: Challenge;
  /** Count today by hand. Absent on a card that cannot be acted on. */
  onCountToday?: (challenge: Challenge) => void;
  /** True while that write is in flight. */
  counting?: boolean;
}

/** How today's state colours the card. Discriminated on the verdict, not on flags. */
const TODAY_TONE: Record<string, string> = {
  done: 'text-emerald-600 dark:text-emerald-400',
  miss: 'text-rose-600 dark:text-rose-400',
  pending: 'text-slate-500 dark:text-slate-400',
};

/**
 * Одно обязательство на экране сегодняшнего дня.
 *
 * Карточка ничего не считает. «День N из M», «промахов K из N» и статус
 * приходят с сервера готовыми — там же, где живёт ленивая материализация, — и
 * второй арифметики обязательства в браузере не заводится.
 */
export default function ChallengeCard({
  challenge,
  onCountToday,
  counting = false,
}: ChallengeCardProps) {
  const tone = challenge.today_verdict
    ? TODAY_TONE[challenge.today_verdict]
    : 'text-slate-500 dark:text-slate-400';
  const showCount = onCountToday !== undefined && canCountToday(challenge);

  return (
    <article
      className="rounded-xl border border-slate-200 dark:border-slate-700 p-4 space-y-2"
      data-testid={`challenge-${challenge.id}`}
    >
      <header className="flex items-center gap-2">
        <Flag className="w-4 h-4 text-slate-400" aria-hidden="true" />
        <h3 className="font-medium text-slate-900 dark:text-slate-100">
          {challenge.title}
        </h3>
        <span className="ml-auto text-xs uppercase tracking-wide text-slate-400">
          {formatStatus(challenge)}
        </span>
      </header>

      <p className="text-sm text-slate-600 dark:text-slate-300">
        {formatProgress(challenge)}, {formatMisses(challenge)}
      </p>

      <div className="flex items-center gap-3">
        <p className={`text-sm ${tone}`}>{formatToday(challenge.today_verdict)}</p>
        {showCount && (
          <button
            type="button"
            className="text-sm text-lime"
            disabled={counting}
            onClick={() => onCountToday(challenge)}
          >
            {counting ? 'Записываю…' : 'Засчитать день'}
          </button>
        )}
      </div>
    </article>
  );
}
