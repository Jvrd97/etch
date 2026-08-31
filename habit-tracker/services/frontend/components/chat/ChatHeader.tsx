'use client';
// [review:need-review] PHASE-03/117
// summary: the header of one conversation — the three token counters and the median latency of the whole dialogue, plus a delete that asks a second time in place instead of through a browser dialog and cannot be pressed twice

import { Trash2 } from 'lucide-react';
import type { ChatUsage } from '@/lib/api';
import { usageSummary } from '@/lib/chat-usage';

/**
 * Состояние кнопки удаления.
 *
 * Union, а не два булевых флага: «спрашиваем» и «удаляем» — это состояния, из
 * которых пара `confirming`/`busy` умеет собрать несуществующее четвёртое.
 */
export type DeleteState = 'idle' | 'confirming' | 'deleting';

interface Props {
  usage: ChatUsage;
  state: DeleteState;
  onAsk: () => void;
  onCancel: () => void;
  onConfirm: () => void;
}

const TITLE = 'Chat';

const SUBTITLE = 'Разговор о дне. История живёт на сервере и переживает перезапуск.';

/** Что удаление сносит. Названо целиком: кнопка не имеет права быть уклончивой. */
const CONFIRM_QUESTION = 'Удалить разговор вместе с сообщениями и файлом сессии?';

export default function ChatHeader({ usage, state, onAsk, onCancel, onConfirm }: Props) {
  return (
    <div>
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-4xl font-bold text-text-primary tracking-tight">
            {TITLE}
            <span className="text-lime">.</span>
          </h1>
          <p className="mt-2 text-text-secondary">{SUBTITLE}</p>
        </div>

        {state === 'idle' && (
          <button
            type="button"
            onClick={onAsk}
            aria-label="Удалить разговор"
            className="inline-flex items-center gap-2 px-4 py-2 rounded-3xl bg-card border border-white/5 text-text-secondary text-sm transition-colors hover:text-danger"
          >
            <Trash2 className="w-4 h-4" strokeWidth={2} />
            Удалить
          </button>
        )}
      </div>

      <p className="mt-3 text-xs text-text-disabled" data-testid="chat-usage">
        Расход подписки: {usageSummary(usage)}
      </p>

      {state !== 'idle' && (
        <div className="mt-4 bg-card border border-danger/40 rounded-3xl px-5 py-4 flex flex-wrap items-center gap-3">
          <p className="text-sm text-text-primary flex-1">{CONFIRM_QUESTION}</p>
          <button
            type="button"
            onClick={onCancel}
            disabled={state === 'deleting'}
            className="px-4 py-2 rounded-3xl bg-surface text-text-secondary text-sm disabled:opacity-40"
          >
            Отмена
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={state === 'deleting'}
            className="px-4 py-2 rounded-3xl bg-danger text-background text-sm font-medium disabled:opacity-40"
          >
            {state === 'deleting' ? 'Удаляю…' : 'Удалить'}
          </button>
        </div>
      )}
    </div>
  );
}
