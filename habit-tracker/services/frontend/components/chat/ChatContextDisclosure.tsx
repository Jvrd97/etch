'use client';
// [review:need-review] PHASE-03/113
// summary: the "что чат видит" disclosure — opens, loads GET /chat/conversations/{id}/context once, and shows the day card verbatim in monospace with its size and what the ceiling ate

import { useCallback, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import type { ChatContext } from '@/lib/api';
import { sizeSummary, truncationNote } from '@/lib/chat-context';

/**
 * Раскрывашка «что чат видит».
 *
 * Показывает карточку дня ровно тем текстом, который ушёл в системный промпт, —
 * без пересказа и без выжимки. Без неё человек не может проверить, откуда взялся
 * ответ, и остаётся один на один с догадкой «модель это выдумала или это правда
 * лежит у меня в базе».
 *
 * Карточка грузится по первому раскрытию, а не вместе с экраном: это двадцать
 * тысяч знаков, которые в свёрнутом виде никто не читает.
 *
 * Чтение приходит пропсом, а не берётся из `@/lib/api` здесь: компонент тогда
 * проверяется без подмены целого модуля API, а экран остаётся единственным
 * местом, которое знает, какой ручкой карточка читается.
 */

export const DISCLOSURE_LABEL = 'Что чат видит';

export const LOADING_TEXT = 'Читаю карточку дня…';

type State =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'failed'; message: string }
  | { status: 'ready'; context: ChatContext };

interface Props {
  conversationId: number;
  load: (conversationId: number) => Promise<ChatContext>;
}

export default function ChatContextDisclosure({ conversationId, load }: Props) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<State>({ status: 'idle' });

  const toggle = useCallback(async () => {
    const next = !open;
    setOpen(next);
    // Повторное раскрытие не перечитывает: карточка уже на экране, и мигать ей
    // незачем. Перечитывается только та, что в прошлый раз не приехала.
    if (!next || state.status === 'ready' || state.status === 'loading') return;
    setState({ status: 'loading' });
    try {
      const context = await load(conversationId);
      setState({ status: 'ready', context });
    } catch (error) {
      setState({
        status: 'failed',
        message: error instanceof Error ? error.message : 'Карточка не прочиталась',
      });
    }
  }, [conversationId, load, open, state.status]);

  const note = state.status === 'ready' ? truncationNote(state.context) : null;

  return (
    <div className="mt-3">
      <button
        type="button"
        onClick={() => void toggle()}
        aria-expanded={open}
        className="inline-flex items-center gap-1.5 text-xs text-text-secondary transition-colors hover:text-text-primary"
      >
        {open ? (
          <ChevronDown className="w-3.5 h-3.5" strokeWidth={2} />
        ) : (
          <ChevronRight className="w-3.5 h-3.5" strokeWidth={2} />
        )}
        {DISCLOSURE_LABEL}
      </button>

      {open && (
        <div className="mt-3 bg-card border border-white/5 rounded-3xl p-4">
          {state.status === 'loading' && (
            <p className="text-xs text-text-disabled">{LOADING_TEXT}</p>
          )}
          {state.status === 'failed' && (
            <p className="text-xs text-danger">{state.message}</p>
          )}
          {state.status === 'ready' && (
            <>
              <p className="text-[11px] text-text-disabled" data-testid="context-size">
                {sizeSummary(state.context)}
              </p>
              {note !== null && (
                <p className="mt-1 text-[11px] text-warning" data-testid="context-note">
                  {note}
                </p>
              )}
              <pre
                data-testid="context-card"
                className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-text-secondary"
              >
                {state.context.text}
              </pre>
            </>
          )}
        </div>
      )}
    </div>
  );
}
