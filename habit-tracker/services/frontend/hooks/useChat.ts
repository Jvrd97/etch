'use client';
// [review:need-review] PHASE-03/118, PHASE-03/116, PHASE-03/114
// summary: PHASE-03/116 adds the turn a refusal produces — 409 while a turn is open, 429 out of slots, 502 from a dead backend — the stored turn left `streaming` by a worker that died, and the reset that unsticks it; chat state for both shells — the conversation named by the link (or the latest one, or a new one), its stored messages in `seq` order, one turn read piece by piece, and the unsent draft mirrored into localStorage so backgrounding the app does not throw it away

import { useCallback, useEffect, useMemo, useState } from 'react';
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

/**
 * Одна выборка, о которой сервер сообщил посреди хода.
 *
 * Живёт только до конца хода: после него разговор перечитывается из таблицы, и
 * та же выборка приезжает строкой `chat_retrievals` под сообщением. Здесь она
 * нужна ровно затем, чтобы сорок секунд ожидания не выглядели как молчание.
 */
export interface LiveRetrieval {
  queryName: string;
  rowCount: number;
  chars: number;
  refusal: string | null;
}

/** Ход в полёте, если он есть. `text` растёт по куску на событие. */
export type ChatTurn =
  | { phase: 'idle' }
  | { phase: 'streaming'; question: string; text: string; retrievals?: LiveRetrieval[] }
  | {
      phase: 'failed';
      question: string;
      text: string;
      code: string;
      retrievals?: LiveRetrieval[];
    };

/**
 * Машинный код отказа, когда сервер отдал его кодом ответа, а не событием.
 *
 * 409 — единственный случай, у которого своего кода в теле нет: диалог занят,
 * и это состояние диалога, а не поломка хода.
 */
export const TURN_IN_FLIGHT = 'turn_in_flight';

/** Что читает человек, когда ход не удался, по машинному коду. */
export const TURN_ERROR_TEXT: Record<string, string> = {
  backend_failed: 'Бэкенд не смог ответить. Ход записан как неудавшийся.',
  first_delta_timeout: 'Бэкенд не сказал ни слова и был остановлен.',
  turn_timeout: 'Ход не уложился в отведённое время и был остановлен.',
  chat_slots_busy: 'Сейчас идут другие разговоры. Попробуйте через минуту.',
  [TURN_IN_FLIGHT]:
    'В этом разговоре ещё идёт ход. Дождитесь ответа или сбросьте зависший.',
};

export const TURN_ERROR_FALLBACK = 'Ход не удался.';

/** Что читает человек рядом с сохранённым сообщением, по его статусу. */
export const MESSAGE_STATUS_NOTE: Record<string, string> = {
  interrupted: 'Ответ оборван — показано то, что успело прийти.',
  streaming: 'Ход не закрыт: похоже, бэкенд перезапустили. Сбросьте разговор.',
};

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
  /**
   * Разговор заперт незакрытым ходом, которого никто уже не ведёт.
   *
   * Отдельно от `busy`: занятость проходит сама, а это — состояние, которое
   * само не рассосётся, и лечится оно кнопкой, а не ожиданием.
   */
  stuck: boolean;
  /** Расклинить разговор: незакрытые ходы становятся оборванными. */
  reset: () => void;
  /** Забыть ошибку экрана и попробовать загрузиться заново. */
  dismissError: () => void;
}

/**
 * Машинный код отказа из ответа сервера.
 *
 * У 429 и 502 в `detail` лежит сам код — сервер отдаёт машинный код и там, где
 * поток ещё не начался. У 409 своего кода нет, потому что это не поломка.
 */
function refusalCode(error: unknown): string | null {
  const status = statusOf(error);
  if (status === null) return null;
  if (status === 409) return TURN_IN_FLIGHT;
  if (status === 429 || status === 502) return (error as Error).message;
  return null;
}

/**
 * Ответ сервера с кодом состояния, узнанный по форме, а не по классу.
 *
 * `instanceof APIError` был бы точнее, но требует, чтобы класс приехал из того
 * же экземпляра модуля `@/lib/api`. В тестах модуль подменяется целиком, а
 * реестр подмен общий на весь прогон: достаточно одного файла, забывшего
 * положить в подмену класс, — и отказ сервера идёт по ветке «экран сломался» в
 * чужом тесте. Форма — имя ошибки и числовой `status` — не зависит от того,
 * чей это экземпляр класса.
 */
function statusOf(error: unknown): number | null {
  if (!(error instanceof Error) || error.name !== 'APIError') return null;
  const status = (error as { status?: unknown }).status;
  return typeof status === 'number' ? status : null;
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
          } else if (event.kind === 'retrieval') {
            setTurn((current) =>
              current.phase === 'streaming'
                ? {
                    ...current,
                    retrievals: [
                      ...(current.retrievals ?? []),
                      {
                        queryName: event.queryName,
                        rowCount: event.rowCount,
                        chars: event.chars,
                        refusal: event.refusal,
                      },
                    ],
                  }
                : current
            );
          } else if (event.kind === 'error') {
            outcome.errorCode = event.code;
          }
        });
      } catch (error) {
        // Отказ ручки — не поломка экрана. 409, 429 и 502 говорят о ходе, а
        // разговор при этом цел и читается; ронять всю ленту в «ошибка» значило
        // бы прятать за ней и уже написанное.
        const code = refusalCode(error);
        if (code === null) {
          setTurn({ phase: 'idle' });
          setScreen({ status: 'failed', message: errorText(error) });
          return;
        }
        setTurn((current) =>
          current.phase === 'streaming' ? { ...current, phase: 'failed', code } : current
        );
        // 409 означает строку, которую никто не закроет: её видно в ленте
        // после перечитывания, и она же запирает разговор.
        if (code === TURN_IN_FLIGHT) {
          const detail = await chatAPI.get(id);
          setMessages(detail.messages);
        }
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

  // Незакрытый ход, приехавший из базы: воркер умер вместе с процессом CLI, и
  // строка осталась в `streaming`. Сервер на такой разговор отвечает 409, так
  // что запирать поле ввода надо до отправки, а не после отказа.
  const stuck = useMemo(
    () => messages.some((message) => message.status === 'streaming'),
    [messages]
  );
  const busy = turn.phase === 'streaming' || stuck;
  const canSend = screen.status === 'ready' && !busy && draft.trim().length > 0;

  const reset = useCallback(() => {
    if (screen.status !== 'ready') return;
    const id = screen.conversationId;
    void (async () => {
      try {
        await chatAPI.reset(id);
        const detail = await chatAPI.get(id);
        setMessages(detail.messages);
        setTurn({ phase: 'idle' });
      } catch (error) {
        setScreen({ status: 'failed', message: errorText(error) });
      }
    })();
  }, [screen]);

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

  return {
    screen,
    messages,
    turn,
    draft,
    setDraft,
    send,
    busy,
    canSend,
    stuck,
    reset,
    dismissError,
  };
}
