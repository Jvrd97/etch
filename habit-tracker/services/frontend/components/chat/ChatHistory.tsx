'use client';
// [review:need-review] PHASE-03/111
// summary: the list of conversations beside the chat — «Новый разговор», the feed broken into the days the conversations started, the open one marked with aria-current, and an unread history told apart from an empty one

import Link from 'next/link';
import { MessagesSquare, Plus } from 'lucide-react';
import type { ChatConversation } from '@/lib/api';
import {
  conversationStamp,
  conversationTitle,
  groupByDay,
} from '@/lib/chat-history';

export const HISTORY_TITLE = 'История';
export const NEW_CONVERSATION = 'Новый разговор';
export const EMPTY_HISTORY = 'Разговоров ещё нет. Первый начнётся с первого вопроса.';

export interface ChatHistoryProps {
  /** Лента, свежие сверху, в порядке сервера. */
  conversations: ChatConversation[];
  /** Открытый разговор, если экран уже знает какой. */
  activeId: number | null;
  /** Сегодняшний день, ISO: по нему группа читается как «Сегодня». */
  today: string;
  /** Ссылка на разговор. Строит вызывающий — оболочки две, а список один. */
  hrefFor: (id: number) => string;
  onStart: () => void;
  /** True, пока разговор заводится: вторая попытка завела бы второй пустой. */
  starting?: boolean;
  /** Почему список пуст, если он пуст не потому, что разговоров нет. */
  error?: string | null;
}

/**
 * История разговоров рядом с самим разговором.
 *
 * Ссылками, а не кнопками: разговор — это адрес (`?conversation=<id>`), и
 * список, переключающий состояние вместо перехода, отнял бы у чата и «назад»,
 * и возможность прислать ссылку на разговор.
 *
 * Открытая строка помечена `aria-current`, а не только цветом: «какой из них
 * сейчас открыт» — вопрос, на который экран обязан отвечать и без цвета.
 */
export default function ChatHistory({
  conversations,
  activeId,
  today,
  hrefFor,
  onStart,
  starting = false,
  error = null,
}: ChatHistoryProps) {
  const groups = groupByDay(conversations, today);

  return (
    <aside className="bg-card border border-white/5 rounded-3xl p-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-medium text-text-secondary">{HISTORY_TITLE}</h2>
      </div>

      <button
        type="button"
        onClick={onStart}
        disabled={starting}
        className="mt-3 w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-3xl bg-lime text-background text-sm font-medium transition-all duration-200 hover:-translate-y-0.5 disabled:opacity-40 disabled:hover:translate-y-0"
      >
        <Plus className="w-4 h-4" strokeWidth={2} />
        {NEW_CONVERSATION}
      </button>

      {error !== null && <p className="mt-4 text-sm text-danger">{error}</p>}

      {error === null && conversations.length === 0 && (
        <div className="mt-6 text-center px-2 pb-2">
          <div className="inline-flex p-3 rounded-3xl bg-surface mb-3">
            <MessagesSquare className="w-5 h-5 text-text-disabled" strokeWidth={2} />
          </div>
          <p className="text-sm text-text-secondary">{EMPTY_HISTORY}</p>
        </div>
      )}

      {groups.map((group) => (
        <section key={group.key} className="mt-5">
          <p className="px-1 text-xs uppercase tracking-wide text-text-disabled">
            {group.label}
          </p>
          <ul className="mt-2 space-y-1">
            {group.conversations.map((one) => {
              const open = one.id === activeId;
              return (
                <li key={one.id}>
                  <Link
                    href={hrefFor(one.id)}
                    aria-current={open ? 'page' : undefined}
                    className={`block px-3 py-2 rounded-2xl transition-colors ${
                      open
                        ? 'bg-lime/15 text-text-primary'
                        : 'text-text-secondary hover:bg-surface'
                    }`}
                  >
                    <span className="block truncate text-sm">
                      {conversationTitle(one)}
                    </span>
                    <span className="mt-0.5 block text-xs text-text-disabled">
                      {conversationStamp(one)}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </aside>
  );
}
