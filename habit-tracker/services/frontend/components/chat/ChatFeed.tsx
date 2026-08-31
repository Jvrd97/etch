'use client';
// [review:need-review] PHASE-03/118, PHASE-03/116, PHASE-03/114
// summary: PHASE-03/116 draws a stored turn by its status — partial text under a note for `interrupted`, the machine code spelled out for `failed`, an unclosed `streaming` row named as such with the button that unsticks it; the conversation feed both shells draw — stored messages as bubbles, the turn in flight growing delta by delta, the machine error code turned into a sentence, and the bottom anchor that keeps the newest line in view while the answer arrives

import { useEffect, useRef } from 'react';
import { MessagesSquare } from 'lucide-react';
import Markdown from '@/components/Markdown';
import ChatRetrievals from '@/components/chat/ChatRetrievals';
import { RETRIEVALS_PREFIX, liveRetrievalLine } from '@/lib/chat-retrievals';
import type { ChatMessage } from '@/lib/api';
import {
  MESSAGE_STATUS_NOTE,
  TURN_ERROR_FALLBACK,
  TURN_ERROR_TEXT,
  type ChatTurn,
} from '@/hooks/useChat';

export interface ChatFeedProps {
  messages: ChatMessage[];
  turn: ChatTurn;
  /** Подсказка на пустой ленте. Разная на широком и на узком экране. */
  emptyHint: string;
  /** Расклинить разговор. Кнопка появляется только у незакрытого хода. */
  onReset?: () => void;
}

export const RESET_LABEL = 'Сбросить зависший ход';

/**
 * Пометка под сохранённым сообщением, либо null у обычного ответа.
 *
 * Оборванный ход показывается своим текстом с пояснением, а не пустотой и не
 * словом «ошибка»: то, что успело прийти, человек уже читал, и отнимать это у
 * него из-за закрытой вкладки не за что.
 */
export function statusNote(message: ChatMessage): string | null {
  if (message.status === 'failed') {
    return message.error_code === null
      ? TURN_ERROR_FALLBACK
      : (TURN_ERROR_TEXT[message.error_code] ?? TURN_ERROR_FALLBACK);
  }
  return MESSAGE_STATUS_NOTE[message.status] ?? null;
}

function Bubble({ role, children }: { role: string; children: React.ReactNode }) {
  const mine = role === 'user';
  return (
    <div className={`flex ${mine ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[90%] px-5 py-3.5 rounded-3xl text-sm leading-relaxed ${
          mine
            ? 'bg-lime text-background font-medium'
            : 'bg-card border border-white/5 text-text-primary'
        }`}
      >
        {children}
      </div>
    </div>
  );
}

/**
 * Лента разговора — одна на обе оболочки.
 *
 * Пузыри, подсказка пустой ленты и расшифровка кода ошибки живут здесь именно
 * для того, чтобы правка любого из трёх текстов была правкой в одном месте:
 * десктопный `/chat` и мобильный `/m/chat` рисуют один и тот же компонент.
 *
 * Ответ модели рисуется размеченным, реплика человека — как есть: markdown в
 * своём же тексте человек не писал, а звёздочки вокруг слова он написать мог.
 * Текущий ход при этом остаётся простым текстом до самого конца — недописанная
 * разметка (открытый блок кода, начатая таблица) на каждом куске перерисовывала
 * бы абзац в мигающий мусор.
 */
export default function ChatFeed({
  messages,
  turn,
  emptyHint,
  onReset,
}: ChatFeedProps) {
  const bottom = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, turn]);

  return (
    <div className="space-y-4">
      {messages.length === 0 && turn.phase === 'idle' && (
        <div className="bg-card border border-white/5 rounded-3xl text-center py-16 px-6">
          <div className="inline-flex p-4 rounded-3xl bg-surface mb-4">
            <MessagesSquare className="w-8 h-8 text-text-disabled" strokeWidth={2} />
          </div>
          <p className="text-text-secondary">{emptyHint}</p>
        </div>
      )}

      {messages.map((message) => {
        const note = statusNote(message);
        return (
          <Bubble key={message.id} role={message.role}>
            {message.role === 'user' ? (
              <span className="whitespace-pre-wrap">{message.content}</span>
            ) : (
              // Незавершённый ответ остаётся простым текстом: недописанная
              // разметка рисуется мусором, а не тем, что человек читал.
              message.status === 'complete' ? (
                <Markdown content={message.content} />
              ) : (
                <span className="whitespace-pre-wrap">{message.content}</span>
              )
            )}
            {note !== null && (
              <p className="mt-2 text-xs text-text-disabled">{note}</p>
            )}
            {/* Что модель достала ради этого ответа. Под текстом, а не над:
                сначала ответ, потом чем он подкреплён. */}
            <ChatRetrievals rows={message.retrievals ?? []} />
            {message.status === 'streaming' && onReset && (
              <button
                type="button"
                onClick={onReset}
                className="mt-2 text-xs text-lime underline underline-offset-2"
              >
                {RESET_LABEL}
              </button>
            )}
          </Bubble>
        );
      })}

      {turn.phase !== 'idle' && (
        <>
          <Bubble role="user">
            <span className="whitespace-pre-wrap">{turn.question}</span>
          </Bubble>
          <Bubble role="assistant">
            {turn.text ? (
              <span className="whitespace-pre-wrap">{turn.text}</span>
            ) : (
              <span className="text-text-disabled">…</span>
            )}
            {(turn.retrievals ?? []).length > 0 && (
              // Идущий ход, ушедший за данными: сорок секунд ожидания иначе
              // неотличимы от зависшего бэкенда.
              <p
                className="mt-2 text-xs text-text-disabled"
                data-testid="turn-retrievals"
              >
                {RETRIEVALS_PREFIX +
                  (turn.retrievals ?? []).map(liveRetrievalLine).join('; ')}
              </p>
            )}
            {turn.phase === 'failed' && (
              <p className="mt-2 text-xs text-danger">
                {TURN_ERROR_TEXT[turn.code] ?? TURN_ERROR_FALLBACK}
              </p>
            )}
          </Bubble>
        </>
      )}
      {/* Якорь прокрутки, а не пустой div: поле ввода на обоих экранах прилипло
          ко дну, и без запаса снизу «прокрутить якорь в видимую часть»
          останавливается ровно за ним. */}
      <div ref={bottom} className="scroll-mb-28" />
    </div>
  );
}
