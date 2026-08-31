// [review:need-review] PHASE-03/127, PHASE-03/128
// summary: pure label helpers of a challenge card — «день N из M», «промахов K из N», the state of today's day and of the challenge itself, and the plural forms Russian needs for both counts

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

/**
 * «промахов 1 из 2» — израсходованный бюджет, а не голое число дней.
 *
 * В режиме `any_miss` бюджета не было, и знаменатель равен нулю. Это честнее
 * отдельной формулировки: «из 0» ровно и значит «ни одного не прощается».
 */
export function formatMisses(challenge: Challenge): string {
  const allowed = challenge.failure_mode === 'budget' ? challenge.allowed_misses : 0;
  const word = plural(challenge.misses_used, 'промах', 'промаха', 'промахов');
  return `${word} ${challenge.misses_used} из ${allowed}`;
}

/** Чем обязательство кончилось — и кончилось ли. */
export function formatStatus(challenge: Challenge): string {
  if (challenge.status === 'won') return 'выигран';
  if (challenge.status === 'abandoned') return 'брошен';
  if (challenge.status === 'failed') {
    return challenge.failed_on ? `завален ${challenge.failed_on}` : 'завален';
  }
  return 'идёт';
}

/**
 * Можно ли засчитать этот день руками прямо с карточки.
 *
 * Только у идущего обязательства и только когда сегодняшний день ещё не
 * засчитан: кнопка «засчитать» на уже засчитанном дне ничего не меняет и
 * только предлагает нажать зря.
 */
export function canCountToday(challenge: Challenge): boolean {
  if (challenge.status === 'won' || challenge.status === 'abandoned') return false;
  return challenge.today_verdict === 'pending' || challenge.today_verdict === 'miss';
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
 * Выигранное и брошенное уходят: они остаются в общем списке как факт, а экран
 * сегодняшнего дня — про то, что делается сегодня.
 */
export function isOnToday(challenge: Challenge): boolean {
  if (challenge.status === 'abandoned' || challenge.status === 'won') return false;
  // Заваленный остаётся на Today: его ещё можно вернуть засчитанным днём, и
  // спрятать его значило бы спрятать единственную кнопку, которая это делает.
  return challenge.today_verdict !== null;
}
