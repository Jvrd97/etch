// [review:need-review] PHASE-03/127
// summary: pure label helpers of a challenge card — «день N из M, промахов K», the state of today's day, and the plural forms Russian needs for both counts

import type { Challenge, ChallengeDayVerdict } from '@/lib/api';

/**
 * Русские формы существительного по числу.
 *
 * Числа на карточке читает человек, а не парсер: «промахов 1» и «день 21 из 30»
 * — это то, что видно на Today каждый день, и склейка через «промах(ов)»
 * читается как незаконченный интерфейс.
 */
export function plural(count: number, one: string, few: string, many: string): string {
  const mod100 = Math.abs(count) % 100;
  const mod10 = mod100 % 10;
  if (mod100 >= 11 && mod100 <= 14) return many;
  if (mod10 === 1) return one;
  if (mod10 >= 2 && mod10 <= 4) return few;
  return many;
}

/** «день 3 из 7» — где обязательство находится в своём окне. */
export function formatProgress(challenge: Challenge): string {
  if (challenge.day_number === 0) {
    return `начнётся, ${challenge.total_days} ${plural(challenge.total_days, 'день', 'дня', 'дней')}`;
  }
  return `день ${challenge.day_number} из ${challenge.total_days}`;
}

/** «промахов 0» — счёт провалов, всегда видимый, а не только когда он ненулевой. */
export function formatMisses(challenge: Challenge): string {
  const word = plural(challenge.misses_used, 'промах', 'промаха', 'промахов');
  return `${word} ${challenge.misses_used}`;
}

/** Что происходит с сегодняшним днём обязательства. */
export function formatToday(verdict: ChallengeDayVerdict | null): string {
  if (verdict === 'done') return 'сегодня сделано';
  if (verdict === 'miss') return 'сегодня промах';
  if (verdict === 'pending') return 'сегодня ещё не подтверждено';
  return 'сегодня вне окна';
}

/**
 * Показывать ли обязательство на Today.
 *
 * Только идущее и только внутри окна: завершённое остаётся в списке как факт,
 * но экран сегодняшнего дня — про то, что делается сегодня.
 */
export function isOnToday(challenge: Challenge): boolean {
  return challenge.status === 'active' && challenge.today_verdict !== null;
}
