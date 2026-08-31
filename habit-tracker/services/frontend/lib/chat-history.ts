// [review:need-review] PHASE-03/111
// summary: the chat feed as a list a person reads — the title the server wrote (or a name for a conversation nobody asked anything), the wall clock of the last reply, and the days the feed breaks into without ever reordering it

import type { ChatConversation } from '@/lib/api';
import { clock } from '@/lib/time';

/** Заголовок разговора, который завели и бросили, не спросив ничего. */
export const UNTITLED_CONVERSATION = 'Разговор без вопроса';

/** Отметка времени такого же разговора: реплик нет, часам взяться неоткуда. */
export const NO_REPLY_YET = 'без реплик';

export const TODAY_LABEL = 'Сегодня';
export const YESTERDAY_LABEL = 'Вчера';

/**
 * Группа для разговора, у которого дня нет.
 *
 * Сервер такого не присылает, но ключ группы — это React-ключ: `undefined`
 * там означает список, который тихо перестаёт различать свои строки. Пусть
 * это будет видимая группа, а не сломанный список.
 */
export const UNKNOWN_DAY_KEY = 'unknown';
export const UNKNOWN_DAY_LABEL = 'Без даты';

/** Разговоры одного дня, в порядке ленты. */
export interface ChatHistoryGroup {
  /** День группы, ISO. Ключ списка: день не меняет смысла между рендерами. */
  key: string;
  /** «Сегодня», «Вчера» или дата словами. */
  label: string;
  conversations: ChatConversation[];
}

const DAY_LABEL_FORMAT: Intl.DateTimeFormatOptions = {
  day: 'numeric',
  month: 'long',
  year: 'numeric',
};

const MS_PER_DAY = 24 * 60 * 60 * 1000;

/**
 * Заголовок строки ленты.
 *
 * Пишет его сервер по первой реплике человека — здесь только случай, когда
 * реплики не было: пустая строка в списке кликабельна, но нечитаема.
 */
export function conversationTitle(one: ChatConversation): string {
  const title = one.title?.trim() ?? '';
  return title.length > 0 ? title : UNTITLED_CONVERSATION;
}

/** Часы последней реплики разговора, как их показывают часы на стене. */
export function conversationStamp(one: ChatConversation): string {
  if (one.last_message_at === null) return NO_REPLY_YET;
  const stamp = clock(one.last_message_at);
  return stamp.length > 0 ? stamp : NO_REPLY_YET;
}

/**
 * Как читается день группы.
 *
 * «Сегодня» и «Вчера» — потому что дата вчерашнего разговора требует счёта в
 * уме ровно тогда, когда ищут разговор «тот, вчерашний».
 */
function dayLabel(day: string, today: string): string {
  if (day === UNKNOWN_DAY_KEY) return UNKNOWN_DAY_LABEL;
  if (day === today) return TODAY_LABEL;
  const gap = Date.parse(`${today}T00:00:00`) - Date.parse(`${day}T00:00:00`);
  if (gap === MS_PER_DAY) return YESTERDAY_LABEL;
  const at = new Date(`${day}T00:00:00`);
  if (Number.isNaN(at.getTime())) return day;
  return at.toLocaleDateString('ru-RU', DAY_LABEL_FORMAT).replace(' г.', '');
}

/**
 * Лента, разбитая по дню, в котором разговор начали.
 *
 * Порядок внутри дня — серверный (`last_message_at`, свежие сверху) и здесь не
 * трогается: второй порядок на экране означал бы, что список и лента отвечают
 * на «какой разговор свежее» по-разному.
 */
export function groupByDay(
  conversations: ChatConversation[],
  today: string
): ChatHistoryGroup[] {
  const groups: ChatHistoryGroup[] = [];
  const byDay = new Map<string, ChatHistoryGroup>();

  for (const one of conversations) {
    const day = one.started_on || UNKNOWN_DAY_KEY;
    const existing = byDay.get(day);
    if (existing !== undefined) {
      existing.conversations.push(one);
      continue;
    }
    const group: ChatHistoryGroup = {
      key: day,
      label: dayLabel(day, today),
      conversations: [one],
    };
    byDay.set(day, group);
    groups.push(group);
  }

  return groups;
}
