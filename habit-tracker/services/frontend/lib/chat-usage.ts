// [review:need-review] PHASE-03/117
// summary: the spend of a conversation put into words — grouped token counts, a latency read in seconds once it passes a second, the header line of three counters, and the per-turn line that makes "the second turn is cheaper than the first" visible instead of merely true

import type { ChatMessage, ChatUsage } from '@/lib/api';

/**
 * Числа расхода в текст.
 *
 * Отдельный модуль, а не разметка внутри экрана: правило «нули не прячем» и
 * порог, с которого задержка читается в секундах, — это решения, у которых
 * должен быть тест. В JSX они непроверяемы.
 *
 * Разряды разделяются обычным пробелом, а не `toLocaleString`: тот отдаёт
 * неразрывный пробел в одной среде и запятую в другой, и тест на строку начал
 * бы зависеть от локали машины, на которой его запустили.
 */

/** С какой задержки читать в секундах, а не в миллисекундах. */
const SECOND_MS = 1000;

/** Разряд группировки числа токенов. */
const GROUP = 3;

/** Разделитель полей одной строки расхода. */
const SEPARATOR = ' · ';

/** Число с пробелами по три разряда: `1200` → `1 200`. */
export function formatTokens(count: number): string {
  const digits = Math.round(Math.abs(count)).toString();
  const groups: string[] = [];
  for (let end = digits.length; end > 0; end -= GROUP) {
    groups.unshift(digits.slice(Math.max(0, end - GROUP), end));
  }
  return `${count < 0 ? '-' : ''}${groups.join(' ')}`;
}

/** Задержка словами; `null`, когда её не замеряли. */
export function formatLatency(ms: number | null): string | null {
  if (ms === null) return null;
  if (ms < SECOND_MS) return `${Math.round(ms)} мс`;
  return `${(ms / SECOND_MS).toFixed(1).replace('.', ',')} с`;
}

/**
 * Строка расхода для шапки разговора.
 *
 * Нули печатаются наравне с остальными числами: «расход неизвестен» и «расход
 * нулевой» — разные факты, и пустая шапка врала бы про первый.
 */
export function usageSummary(usage: ChatUsage): string {
  const parts = [
    `вход ${formatTokens(usage.input_tokens)}`,
    `выход ${formatTokens(usage.output_tokens)}`,
    `из кеша ${formatTokens(usage.cache_read_tokens)}`,
  ];
  const latency = formatLatency(usage.latency_ms_median);
  if (latency !== null) parts.push(`медиана ${latency}`);
  return parts.join(SEPARATOR);
}

/**
 * Чем обошёлся один ход; `null`, когда счётчиков у сообщения нет.
 *
 * Реплика человека и ход, упавший до ответа, счётчиков не имеют, и строка «0 ·
 * 0 · 0» под ними была бы не фактом, а шумом.
 */
export function turnCost(message: ChatMessage): string | null {
  const { input_tokens: input, output_tokens: output } = message;
  if (input === null && output === null && message.cache_read_tokens === null) {
    return null;
  }
  const parts = [
    `вход ${formatTokens(input ?? 0)}`,
    `выход ${formatTokens(output ?? 0)}`,
    `из кеша ${formatTokens(message.cache_read_tokens ?? 0)}`,
  ];
  const latency = formatLatency(message.latency_ms);
  if (latency !== null) parts.push(latency);
  return parts.join(SEPARATOR);
}
