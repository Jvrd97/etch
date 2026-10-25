'use client';
// [review:need-review] PHASE-03/111, PHASE-03/197
// summary: PHASE-03/197 adds `remove` — the one deletion both shells share: a row leaves the list only after the server answered, one deletion at a time, a refusal comes back as words for the row instead of an error for the whole list, and a conversation already gone counts as deleted
// summary: the list of conversations behind the chat screen — one read of the feed, a new conversation that lands on top before the re-read, a failed read named rather than shown as an empty history, and a re-read the screen asks for after every turn

import { useCallback, useEffect, useRef, useState } from 'react';
import { chatAPI, type ChatConversation } from '@/lib/api';

/** Сколько разговоров держит список. Столько же отдаёт сервер по умолчанию. */
const HISTORY_LIMIT = 50;

const HTTP_NOT_FOUND = 404;
const HTTP_CONFLICT = 409;

/** Сервер не удаляет разговор, пока в нём пишется ответ: 409 на DELETE. */
export const REMOVE_RUNNING_ANSWER =
  'В разговоре ещё идёт ответ. Дождитесь его конца или сбросьте зависший ход, потом удалите.';
export const REMOVE_BUSY = 'Другой разговор уже удаляется. Дождитесь конца.';

/**
 * Итог удаления. Union, а не исключение: отказ — обычный исход, который
 * строка списка показывает словами, а не обрывает экран.
 */
export type RemoveOutcome = { ok: true } | { ok: false; message: string };

export interface UseChatHistoryResult {
  /** Лента, свежие сверху — в порядке, который прислал сервер. */
  conversations: ChatConversation[];
  /** True, пока лента ещё не прочитана ни разу. */
  loading: boolean;
  /** True, пока заводится новый разговор. */
  starting: boolean;
  /** Разговор, который удаляется прямо сейчас. */
  removing: number | null;
  /** Почему история не прочиталась или не завёлся разговор. */
  error: string | null;
  /**
   * Завести разговор и вернуть его id — экран сразу переходит на него.
   * `null` означает отказ сервера; история при этом остаётся прежней.
   */
  start: () => Promise<number | null>;
  /**
   * Удалить разговор. Строка уходит из списка только после ответа сервера, а
   * отказ возвращается словами для этой строки: ошибка ленты (`error`) говорит
   * «список не прочитался», и про удаление это была бы неправда.
   */
  remove: (id: number) => Promise<RemoveOutcome>;
  /** Перечитать ленту: после хода у разговора меняются заголовок и время. */
  reload: () => void;
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'Unknown error';
}

/**
 * Код ответа сервера, узнанный по форме ошибки, а не по классу: в тестах
 * модуль `@/lib/api` подменяется целиком, и `instanceof` там не сработает
 * (то же объяснение — в `useChat.ts`, `statusOf`).
 */
function statusOf(error: unknown): number | null {
  if (!(error instanceof Error) || error.name !== 'APIError') return null;
  const status = (error as { status?: unknown }).status;
  return typeof status === 'number' ? status : null;
}

/**
 * История разговоров.
 *
 * Отдельный срез от самого разговора, и намеренно: лента перечитывается после
 * каждого хода (заголовок разговору пишет сервер по первой реплике), а сам
 * разговор — нет. Держать их одним состоянием значило бы перечитывать ленту
 * ради ответа и ответ ради ленты.
 *
 * Заведённый разговор встаёт в начало списка до перечитывания. Экран переходит
 * на него сразу — и строка, на которую человек смотрит, обязана уже быть в
 * списке, а не появиться через круг до сервера.
 */
export function useChatHistory(): UseChatHistoryResult {
  const [conversations, setConversations] = useState<ChatConversation[]>([]);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [removing, setRemoving] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  // Защёлка, а не `starting`: два клика подряд попадают в один рендер, видят
  // одно и то же состояние и заводят два разговора. Ref меняется сразу.
  const inFlight = useRef(false);
  // Та же защёлка для удаления: двойной клик по «Удалить» не должен послать
  // второй запрос на тот же разговор.
  const removeInFlight = useRef(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const feed = await chatAPI.list(HISTORY_LIMIT);
        if (cancelled) return;
        setConversations(feed);
        setError(null);
      } catch (failure) {
        // Список остаётся пустым, но с названной причиной: пустая история и
        // непрочитанная — разные ответы на «где мои разговоры».
        if (!cancelled) setError(errorText(failure));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const start = useCallback(async (): Promise<number | null> => {
    // Второй клик по «Новому разговору», пока идёт первый, завёл бы второй
    // пустой разговор — и человек оказался бы не в том, куда его увели.
    if (inFlight.current) return null;
    inFlight.current = true;
    setStarting(true);
    setError(null);
    try {
      const started = await chatAPI.create();
      setConversations((current) => [started, ...current]);
      return started.id;
    } catch (failure) {
      setError(errorText(failure));
      return null;
    } finally {
      inFlight.current = false;
      setStarting(false);
    }
  }, []);

  const remove = useCallback(async (id: number): Promise<RemoveOutcome> => {
    if (removeInFlight.current) return { ok: false, message: REMOVE_BUSY };
    removeInFlight.current = true;
    setRemoving(id);
    try {
      await chatAPI.remove(id);
    } catch (failure) {
      const status = statusOf(failure);
      // 404 — разговор уже удалён (другой вкладкой): цель достигнута, строке
      // с кнопкой, которая будет получать 404 вечно, в списке делать нечего.
      if (status !== HTTP_NOT_FOUND) {
        const message =
          status === HTTP_CONFLICT
            ? REMOVE_RUNNING_ANSWER
            : `Не удалось удалить разговор: ${errorText(failure)}. Попробуйте ещё раз.`;
        return { ok: false, message };
      }
    } finally {
      removeInFlight.current = false;
      setRemoving(null);
    }
    setConversations((current) => current.filter((one) => one.id !== id));
    return { ok: true };
  }, []);

  const reload = useCallback(() => {
    setAttempt((current) => current + 1);
  }, []);

  return { conversations, loading, starting, removing, error, start, remove, reload };
}
