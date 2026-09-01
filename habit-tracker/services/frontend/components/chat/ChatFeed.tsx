'use client';
// [review:need-review] PHASE-03/118, PHASE-03/116, PHASE-03/114, PHASE-03/120, PHASE-03/189
// summary: PHASE-03/120 makes the wait legible — the thought of the model as a collapsed line above the answer, three breathing dots until the first word, a caret while the text arrives, and a copy button on every message
// summary: PHASE-03/116 draws a stored turn by its status — partial text under a note for `interrupted`, the machine code spelled out for `failed`, an unclosed `streaming` row named as such with the button that unsticks it; the conversation feed both shells draw — stored messages as bubbles, the turn in flight growing delta by delta, the machine error code turned into a sentence, and the bottom anchor that keeps the newest line in view while the answer arrives

import { useEffect, useRef } from 'react';
import { MessagesSquare } from 'lucide-react';
import Markdown from '@/components/Markdown';
import ChatBubble from '@/components/chat/ChatBubble';
import ChatRetrievals from '@/components/chat/ChatRetrievals';
import ThinkingBlock from '@/components/chat/ThinkingBlock';
import { StreamingCaret, WaitingDots } from '@/components/chat/TurnLive';
import { visibleAnswer } from '@/lib/chat-answer';
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
        // Служебные блоки — `need` и `plan` — из пузыря вырезаются: первый
        // отражён строкой выборки под ответом, второй плашкой. Сохранённое
        // сообщение цело, режется только показ.
        const shown = visibleAnswer(message.content);
        return (
          // Копируется само сообщение, а не пузырь: пометки ленты — «ответ
          // оборван», «запрошено: …» — это подписи экрана, а не сказанное.
          <ChatBubble key={message.id} role={message.role} copyText={shown}>
            {message.role === 'user' ? (
              <span className="whitespace-pre-wrap break-words">{shown}</span>
            ) : (
              // Незавершённый ответ остаётся простым текстом: недописанная
              // разметка рисуется мусором, а не тем, что человек читал.
              message.status === 'complete' ? (
                <Markdown content={shown} />
              ) : (
                <span className="whitespace-pre-wrap break-words">{shown}</span>
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
          </ChatBubble>
        );
      })}

      {turn.phase !== 'idle' && (
        <>
          <ChatBubble role="user" copyText={turn.question}>
            <span className="whitespace-pre-wrap break-words">{turn.question}</span>
          </ChatBubble>
          <ChatBubble role="assistant" copyText={visibleAnswer(turn.text)}>
            {/* Мысль стоит над ответом и отдельно от него: это разные тексты, и
                общий узел разметки был бы первым шагом к тому, чтобы они
                склеились в один. */}
            <ThinkingBlock progress={turn.progress} answering={turn.text.length > 0} />
            {visibleAnswer(turn.text) ? (
              <span className="whitespace-pre-wrap break-words">
                {visibleAnswer(turn.text)}
                {/* Курсор в конце последнего куска: текст идёт, ход не кончился. */}
                {turn.phase === 'streaming' && <StreamingCaret />}
              </span>
            ) : turn.phase === 'streaming' ? (
              // До первого слова единственный честный ответ на «оно работает?» —
              // признак жизни. Три точки, а не многоточие: многоточие не
              // отличает идущий ход от повисшего.
              <WaitingDots />
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
          </ChatBubble>
        </>
      )}
      {/* Якорь прокрутки, а не пустой div: поле ввода на обоих экранах прилипло
          ко дну, и без запаса снизу «прокрутить якорь в видимую часть»
          останавливается ровно за ним. */}
      <div ref={bottom} className="scroll-mb-28" />
    </div>
  );
}
