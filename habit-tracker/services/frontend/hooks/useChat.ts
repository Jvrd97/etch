'use client';
// [review:need-review] PHASE-03/118
// summary: chat state for both shells — the conversation named by the link (or the latest one, or a new one), its stored messages in `seq` order, one turn read piece by piece, and the unsent draft mirrored into localStorage so backgrounding the app does not throw it away

import { useCallback, useEffect, useState } from 'react';
import { chatAPI, type ChatMessage } from '@/lib/api';
import type { ChatStreamEvent } from '@/lib/chat-stream';
import {
  browserDraftStorage,
  clearChatDraft,
  readChatDraft,
  writeChatDraft,
  type DraftStorage,
} from '@/lib/chat-draft';

/**
 * Состояние экрана чата.
 *
 * Объединение, а не три булевых: «загрузка провалилась» и «готов, но разговора
 * нет» — состояния, которые тройка флагов умеет изобразить, а этот экран не
 * принимает никогда.
 */
export type ChatScreen =
  | { status: 'loading' }
  | { status: 'failed'; message: string }
  | { status: 'ready'; conversationId: number };

/** Ход в полёте, если он есть. `text` растёт по куску на событие. */
export type ChatTurn =
  | { phase: 'idle' }
  | { phase: 'streaming'; question: string; text: string }
  | { phase: 'failed'; question: string; text: string; code: string };

/** Что читает человек, когда бэкенд отказал ходу, по машинному коду. */
export const TURN_ERROR_TEXT: Record<string, string> = {
  backend_failed: 'Бэкенд не смог ответить. Ход записан как неудавшийся.',
};

export const TURN_ERROR_FALLBACK = 'Ход не удался.';

export interface UseChatOptions {
  /**
   * Разговор, который открывает ссылка. `null` — «свежий, а если его нет,
   * заведи»: так экран чата открывается из «More», без ссылки на конкретный
   * день.
   */
  conversationId?: number | null;
  /** Хранилище черновика. Подменяется в тестах; по умолчанию — localStorage. */
  storage?: DraftStorage | null;
}

/** Всё, что нужно экрану чата; две оболочки различаются только разметкой. */
export interface UseChatResult {
  screen: ChatScreen;
  messages: ChatMessage[];
  turn: ChatTurn;
  /** Набранный, ещё не отправленный текст. */
  draft: string;
  setDraft: (text: string) => void;
  /** Отправить набранное. Ничего не делает, когда отправлять нечего. */
  send: () => void;
  /** True, пока ход идёт: поле ввода заперто, второй ход не начать. */
  busy: boolean;
  /** True, когда есть что отправить и ход не идёт. */
  canSend: boolean;
  /** Забыть ошибку экрана и попробовать загрузиться заново. */
  dismissError: () => void;
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'Unknown error';
}

/**
 * Состояние разговора, общее для `/chat` и `/m/chat`.
 *
 * Логика живёт здесь целиком, потому что иначе она живёт дважды: два экрана
 * одного разговора — ровно тот случай, когда правка текста ошибки или порядка
 * событий потока начинает требоваться в двух местах.
 *
 * Черновик пишется в хранилище на каждое изменение поля, а не по таймеру:
 * приложение на телефоне сворачивают без предупреждения, и «сохраним через
 * секунду» — это ровно та секунда, в которую текст и теряется.
 */
export function useChat(options: UseChatOptions = {}): UseChatResult {
  const { conversationId = null } = options;
  // Хранилище берётся один раз и не пересчитывается: `window` на сервере нет,
  // а после гидратации оно уже не меняется.
  const [storage] = useState<DraftStorage | null>(
    () => options.storage ?? browserDraftStorage()
  );

  const [screen, setScreen] = useState<ChatScreen>({ status: 'loading' });
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [turn, setTurn] = useState<ChatTurn>({ phase: 'idle' });
  const [draft, setDraftState] = useState('');
  // Растёт на каждый `dismissError`: экран просят загрузиться заново.
  const [attempt, setAttempt] = useState(0);
  // Разговор, под который выставлено текущее состояние. Сравнение прямо в
  // рендере — тот самый способ сбросить состояние на смену входа, который React
  // и предлагает вместо эффекта: иначе ссылка на другой разговор оставила бы на
  // экране ленту предыдущего до самого ответа сервера.
  const [shown, setShown] = useState<number | null>(conversationId);
  if (shown !== conversationId) {
    setShown(conversationId);
    setScreen({ status: 'loading' });
    setMessages([]);
    setDraftState('');
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // Разговор, названный ссылкой, — если он есть. Иначе одна лента на
        // экран: берётся свежий разговор, а нет его — заводится. Список
        // разговоров — отдельный срез, не этот.
        const id =
          conversationId ??
          ((await chatAPI.list(1))[0] ?? (await chatAPI.create())).id;
        const detail = await chatAPI.get(id);
        if (cancelled) return;
        setMessages(detail.messages);
        // Черновик восстанавливается вместе с разговором, а не при монтировании:
        // до ответа сервера неизвестно, черновик какого разговора показывать.
        setDraftState(readChatDraft(storage, id));
        setScreen({ status: 'ready', conversationId: id });
      } catch (error) {
        if (!cancelled) setScreen({ status: 'failed', message: errorText(error) });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [conversationId, storage, attempt]);

  const setDraft = useCallback(
    (text: string) => {
      setDraftState(text);
      if (screen.status === 'ready') writeChatDraft(storage, screen.conversationId, text);
    },
    [screen, storage]
  );

  const runTurn = useCallback(
    async (id: number, question: string) => {
      setTurn({ phase: 'streaming', question, text: '' });
      // Хранится в объекте, а не в `let`: присваивание происходит внутри
      // колбэка, и TypeScript сузил бы обычную локальную переменную до `null`
      // на каждой строке после цикла.
      const outcome: { errorCode: string | null } = { errorCode: null };
      try {
        await chatAPI.streamMessage(id, question, (event: ChatStreamEvent) => {
          if (event.kind === 'delta') {
            setTurn((current) =>
              current.phase === 'streaming'
                ? { ...current, text: current.text + event.text }
                : current
            );
          } else if (event.kind === 'error') {
            outcome.errorCode = event.code;
          }
        });
      } catch (error) {
        setTurn({ phase: 'idle' });
        setScreen({ status: 'failed', message: errorText(error) });
        return;
      }

      const errorCode = outcome.errorCode;
      if (errorCode !== null) {
        setTurn((current) =>
          current.phase === 'streaming' ? { ...current, phase: 'failed', code: errorCode } : current
        );
        return;
      }

      // Перечитывание вместо склейки в памяти: строки таблицы и есть разговор,
      // и именно они переживут перезагрузку.
      const detail = await chatAPI.get(id);
      setMessages(detail.messages);
      setTurn({ phase: 'idle' });
    },
    []
  );

  const busy = turn.phase === 'streaming';
  const canSend = screen.status === 'ready' && !busy && draft.trim().length > 0;

  const send = useCallback(() => {
    if (screen.status !== 'ready' || busy) return;
    const question = draft.trim();
    if (question.length === 0) return;
    // Черновик гасится здесь, а не по завершении хода: реплика уже ушла в
    // разговор, и вернуть её в поле ввода означало бы предложить отправить её
    // второй раз. Неудача хода не возвращает текст — он лежит в ленте.
    setDraftState('');
    clearChatDraft(storage, screen.conversationId);
    void runTurn(screen.conversationId, question);
  }, [screen, busy, draft, storage, runTurn]);

  // Сброс в «загрузку» стоит здесь, а не в эффекте: это обработчик нажатия, и
  // повторная попытка обязана убрать сообщение об ошибке сразу, а не после
  // следующего ответа сервера.
  const dismissError = useCallback(() => {
    setScreen({ status: 'loading' });
    setAttempt((current) => current + 1);
  }, []);

  return { screen, messages, turn, draft, setDraft, send, busy, canSend, dismissError };
}
