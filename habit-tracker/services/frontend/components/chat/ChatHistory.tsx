'use client';
// [review:need-review] PHASE-03/111, PHASE-03/203
// summary: PHASE-03/203 lets the same list live in the phone's history panel — a `panel` layout that scrolls inside its container at every width, a list still being read, a retry for a failed read, and a picked row reported to the caller
// summary: the list of conversations beside the chat — «Новый разговор», the feed broken into the days the conversations started, the open one marked with aria-current, an unread history told apart from an empty one, and the whole column pinned so it stays in place while the conversation scrolls

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
export const HISTORY_LOADING = 'Читаю разговоры…';
export const HISTORY_RETRY = 'Повторить';

/**
 * Где стоит список.
 *
 * `column` — колонка рядом с разговором на `/chat`: на широком экране она
 * закреплена во всю высоту окна, на узком становится блоком сверху. `panel` —
 * мобильная панель истории: высоту задаёт панель, и список прокручивается
 * внутри неё при любой ширине окна, а заголовок несёт сама панель.
 */
export type ChatHistoryLayout = 'column' | 'panel';

const FRAME_CLASS: Record<ChatHistoryLayout, string> = {
  column:
    'bg-card border border-white/5 rounded-3xl p-4 lg:sticky lg:top-4 lg:flex lg:flex-col lg:h-[calc(100vh-2rem)]',
  panel: 'flex flex-1 min-h-0 flex-col px-4 pt-1',
};

const LIST_CLASS: Record<ChatHistoryLayout, string> = {
  column: 'lg:flex-1 lg:min-h-0 lg:overflow-y-auto lg:-mr-2 lg:pr-2',
  panel:
    'flex-1 min-h-0 overflow-y-auto -mr-2 pr-2 pb-[calc(env(safe-area-inset-bottom)+1rem)]',
};

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
  /** True, пока лента не прочитана ни разу: пустой список ещё не значит «нет». */
  loading?: boolean;
  /** Прочитать ленту заново. Без него у ошибки нет кнопки повтора. */
  onRetry?: () => void;
  /** Строку выбрали. Панель закрывается и тогда, когда адрес не меняется. */
  onPick?: (id: number) => void;
  layout?: ChatHistoryLayout;
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
 *
 * Колонка закреплена и живёт во всю высоту окна, а не стоит карточкой вверху
 * страницы: длинный разговор прокручивается на несколько экранов, и список,
 * уехавший вверх вместе с ним, перестаёт быть навигацией — до него надо
 * возвращаться.
 *
 * Прокручивается внутри колонки только сам список. «Новый разговор» остаётся
 * на месте: действие, до которого надо доскроллить, — это действие, которого на
 * экране нет. На узком экране колонка снова становится обычным блоком сверху:
 * там она одна, прокручивать её отдельно нечего и незачем.
 */
export default function ChatHistory({
  conversations,
  activeId,
  today,
  hrefFor,
  onStart,
  starting = false,
  error = null,
  loading = false,
  onRetry,
  onPick,
  layout = 'column',
}: ChatHistoryProps) {
  const groups = groupByDay(conversations, today);
  const unread = error === null && conversations.length === 0;

  return (
    <aside className={FRAME_CLASS[layout]}>
      {layout === 'column' && (
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-sm font-medium text-text-secondary">{HISTORY_TITLE}</h2>
        </div>
      )}

      <button
        type="button"
        onClick={onStart}
        disabled={starting}
        className="mt-3 w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-3xl bg-lime text-background text-sm font-medium transition-all duration-200 hover:-translate-y-0.5 disabled:opacity-40 disabled:hover:translate-y-0"
      >
        <Plus className="w-4 h-4" strokeWidth={2} />
        {NEW_CONVERSATION}
      </button>

      {/* Прокручивается только список: кнопка «Новый разговор» и заголовок
          стоят на месте, потому что действие, до которого надо доскроллить,
          на экране отсутствует. */}
      <div className={LIST_CLASS[layout]}>
      {error !== null && (
        <div className="mt-4 space-y-2">
          <p className="text-sm text-danger">{error}</p>
          {onRetry && (
            <button
              type="button"
              onClick={onRetry}
              className="text-sm font-medium text-lime underline-offset-4 hover:underline"
            >
              {HISTORY_RETRY}
            </button>
          )}
        </div>
      )}

      {unread && loading && (
        <p role="status" className="mt-6 text-center text-sm text-text-disabled">
          {HISTORY_LOADING}
        </p>
      )}

      {unread && !loading && (
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
                    onClick={onPick && (() => onPick(one.id))}
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
      </div>
    </aside>
  );
}
