// [review:need-review] PHASE-03/118
// summary: the unsent message of one conversation, kept in localStorage under a per-conversation key so backgrounding the app on a phone does not throw away a half-written reply; an empty draft is an absent key, and a storage that refuses to write is not an error the typing surface has to handle

/**
 * Черновик реплики, переживающий сворачивание приложения.
 *
 * Ключ несёт id разговора: два разговора набираются независимо, и черновик,
 * общий на весь чат, подставил бы недописанное сообщение в чужую ленту.
 *
 * **Пустой черновик — это отсутствующий ключ, а не пустая строка.** Иначе
 * localStorage копит по записи на каждый когда-либо открытый разговор, и
 * очистка после отправки перестаёт быть очисткой.
 */

/** Префикс ключей черновиков. Один разговор — один ключ. */
export const CHAT_DRAFT_KEY_PREFIX = 'habit-tracker:chat-draft:';

/** Та часть Web Storage, которая здесь нужна. Позволяет тесту дать свою. */
export interface DraftStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

/** Ключ черновика разговора. */
export function chatDraftKey(conversationId: number): string {
  return `${CHAT_DRAFT_KEY_PREFIX}${conversationId}`;
}

/**
 * Хранилище браузера, или `null` на сервере.
 *
 * Возвращается `null`, а не заглушка: вызывающий и так обязан пережить отказ
 * хранилища, и вторая ветка «заглушка против настоящего» ему ничего не даёт.
 */
export function browserDraftStorage(): DraftStorage | null {
  if (typeof window === 'undefined') return null;
  return window.localStorage;
}

/**
 * Черновик разговора; пустая строка, если его нет.
 *
 * Чтение localStorage бросает в приватном режиме Safari и при запрете на
 * хранение данных сайта. Ловится молча и намеренно: отсутствие черновика —
 * штатное состояние экрана, а не сбой, о котором есть что сказать человеку.
 * Логировать здесь тоже нечего: в исключении лежит только имя ключа, а его
 * содержимое — текст человека, которому в логах не место.
 */
export function readChatDraft(
  storage: DraftStorage | null,
  conversationId: number
): string {
  if (!storage) return '';
  try {
    return storage.getItem(chatDraftKey(conversationId)) ?? '';
  } catch {
    return '';
  }
}

/**
 * Запомнить черновик. Текст из одних пробелов — то же самое, что пустой:
 * отправить его нельзя, и хранить незачем.
 *
 * Отказ хранилища не мешает набирать текст дальше — он лишь означает, что
 * набранное не переживёт сворачивания. Бросить отсюда значит уронить обработчик
 * ввода, то есть отнять у человека и сам набор.
 */
export function writeChatDraft(
  storage: DraftStorage | null,
  conversationId: number,
  text: string
): void {
  if (!storage) return;
  if (text.trim().length === 0) {
    clearChatDraft(storage, conversationId);
    return;
  }
  try {
    storage.setItem(chatDraftKey(conversationId), text);
  } catch {
    return;
  }
}

/** Забыть черновик — то, что делает удавшаяся отправка. */
export function clearChatDraft(
  storage: DraftStorage | null,
  conversationId: number
): void {
  if (!storage) return;
  try {
    storage.removeItem(chatDraftKey(conversationId));
  } catch {
    return;
  }
}
