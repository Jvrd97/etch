'use client';
// [review:need-review] PHASE-03/127
// summary: the Today card of one obligation — «день N из M, промахов K» plus the state of today's day, with every number taken from the server response rather than recounted here

import { Flag } from 'lucide-react';
import type { Challenge } from '@/lib/api';
import { formatMisses, formatProgress, formatToday } from '@/lib/challenges';

interface ChallengeCardProps {
  challenge: Challenge;
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
 * Карточка ничего не считает. `день N из M` и `промахов K` приходят с сервера
 * готовыми — там же, где живёт ленивая материализация, — и второй арифметики
 * обязательства в браузере не заводится.
 */
export default function ChallengeCard({ challenge }: ChallengeCardProps) {
  const tone = challenge.today_verdict
    ? TODAY_TONE[challenge.today_verdict]
    : 'text-slate-500 dark:text-slate-400';

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
      </header>

      <p className="text-sm text-slate-600 dark:text-slate-300">
        {formatProgress(challenge)}, {formatMisses(challenge)}
      </p>

      <p className={`text-sm ${tone}`}>{formatToday(challenge.today_verdict)}</p>
    </article>
  );
}
