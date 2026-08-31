// [review:need-review] PHASE-03/112
// summary: what the conversation header says about the price of the next turn — whether it continues a CLI session or rebuilds the dialogue from the table, and what the last turn actually read from cache

import type { ChatMessage } from '@/lib/api';

/**
 * How the next turn will be paid for.
 *
 * A union rather than a boolean plus a string: "продолжение" without a session
 * and "пересбор" with cached tokens are states a boolean pair can represent and
 * this screen never has.
 */
export type ResumeMode =
  | { kind: 'resume'; label: string; hint: string }
  | { kind: 'replay'; label: string; hint: string };

const RESUME_LABEL = 'Продолжение сессии';
const REPLAY_LABEL = 'Полный пересбор';

const RESUME_HINT =
  'Следующий ход платит только за новую реплику: остальное уже в кеше сессии.';
const REPLAY_HINT =
  'Следующий ход соберёт разговор из истории целиком — дороже, но ответ тот же.';

/**
 * The badge of the conversation header.
 *
 * The server answers whether a session is there to continue — four conditions
 * live behind that flag, and the browser has no way to check any of them.
 */
export function resumeMode(resumeReady: boolean): ResumeMode {
  return resumeReady
    ? { kind: 'resume', label: RESUME_LABEL, hint: RESUME_HINT }
    : { kind: 'replay', label: REPLAY_LABEL, hint: REPLAY_HINT };
}

/**
 * What the last answered turn read from cache, or null when nothing did.
 *
 * This is the number that makes the difference visible: without it "продолжение
 * сессии" is a word, and the price of a turn stays invisible. Messages are
 * scanned from the end because only the latest turn describes the state the
 * next one starts from.
 */
export function lastCacheRead(messages: readonly ChatMessage[]): number | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message.role !== 'assistant') continue;
    const cached = message.cache_read_tokens;
    return cached !== null && cached > 0 ? cached : null;
  }
  return null;
}
