'use client';
// [review:need-review] PHASE-03/111
// summary: the list of conversations behind the chat screen — one read of the feed, a new conversation that lands on top before the re-read, a failed read named rather than shown as an empty history, and a re-read the screen asks for after every turn

import { useCallback, useEffect, useRef, useState } from 'react';
import { chatAPI, type ChatConversation } from '@/lib/api';

/** Сколько разговоров держит список. Столько же отдаёт сервер по умолчанию. */
const HISTORY_LIMIT = 50;

export interface UseChatHistoryResult {
  /** Лента, свежие сверху — в порядке, который прислал сервер. */
  conversations: ChatConversation[];
  /** True, пока лента ещё не прочитана ни разу. */
  loading: boolean;
  /** True, пока заводится новый разговор. */
  starting: boolean;
  /** Почему история не прочиталась или не завёлся разговор. */
  error: string | null;
  /**
   * Завести разговор и вернуть его id — экран сразу переходит на него.
   * `null` означает отказ сервера; история при этом остаётся прежней.
   */
  start: () => Promise<number | null>;
  /** Перечитать ленту: после хода у разговора меняются заголовок и время. */
  reload: () => void;
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'Unknown error';
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
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  // Защёлка, а не `starting`: два клика подряд попадают в один рендер, видят
  // одно и то же состояние и заводят два разговора. Ref меняется сразу.
  const inFlight = useRef(false);

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

  const reload = useCallback(() => {
    setAttempt((current) => current + 1);
  }, []);

  return { conversations, loading, starting, error, start, reload };
}
