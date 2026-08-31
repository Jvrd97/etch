// [review:need-review] PHASE-03/118
// summary: where a link into the chat points — the conversation named in the query string, and the chat route of the shell the reader is already in, so a button pressed inside /m stays inside /m

import { MOBILE_PATH_PREFIX } from './routes';
import { toMobilePath } from './view-mode';

/**
 * Ссылки внутрь чата.
 *
 * Разговор назван в query, а не выбран экраном: «спросить про день» заводит
 * разговор именно этого дня, и открывать после этого «самый свежий» — значит
 * рассчитывать на то, что между созданием и переходом ничего не появилось.
 */

/** Имя параметра, которым экран чата узнаёт, какой разговор открывать. */
export const CHAT_CONVERSATION_PARAM = 'conversation';

/** Десктопный маршрут чата. Мобильный близнец выводится из него. */
export const CHAT_PATH = '/chat';

/**
 * Маршрут чата для оболочки, в которой человек уже находится.
 *
 * Кнопка на `/m/today` обязана вести на `/m/chat`, а не выкидывать из
 * мобильной оболочки на десктопную страницу. `toMobilePath` берёт ответ из
 * реестра маршрутов, поэтому пока у чата нет мобильного близнеца, обе оболочки
 * честно ведут на `/chat`.
 */
export function chatPathFor(pathname: string): string {
  const inMobileShell =
    pathname === MOBILE_PATH_PREFIX || pathname.startsWith(`${MOBILE_PATH_PREFIX}/`);
  if (!inMobileShell) return CHAT_PATH;
  return toMobilePath(CHAT_PATH) ?? CHAT_PATH;
}

/** Тот же маршрут, но с уже открытым разговором. */
export function chatHrefFor(pathname: string, conversationId: number): string {
  return `${chatPathFor(pathname)}?${CHAT_CONVERSATION_PARAM}=${conversationId}`;
}

/**
 * Разговор, названный в query, или `null`.
 *
 * Мусор в параметре — это `null`, а не ошибка: ссылку правят руками, и экран,
 * падающий на `?conversation=abc`, хуже экрана, открывающего свежий разговор.
 */
export function conversationIdFrom(params: URLSearchParams): number | null {
  const raw = params.get(CHAT_CONVERSATION_PARAM);
  if (raw === null) return null;
  const parsed = Number(raw);
  if (!Number.isInteger(parsed) || parsed <= 0) return null;
  return parsed;
}
