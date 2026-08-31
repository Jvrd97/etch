'use client';
// [review:need-review] PHASE-03/97
// summary: inbox state — the feed of signals beside the directory of sources, one manual poll at a time with its refusal read as a machine code rather than as a sentence, and a re-read of the feed after a poll that brought something

import { useCallback, useEffect, useRef, useState } from 'react';
import { inboxAPI, type InboundSignal, type SignalSource } from '@/lib/api';

/** Что показывает экран, когда источник отказал. По машинному коду сервера. */
export const REFUSAL_TEXT: Record<string, string> = {
  source_disabled: 'Источник выключен — включите его, чтобы читать.',
  no_adapter: 'У источника нет адаптера: строка в справочнике есть, читать нечем.',
  no_credentials: 'Токена нет: переменная окружения пуста. В базе токен не хранится.',
  transport_failed: 'Источник недоступен.',
};

export const REFUSAL_FALLBACK = 'Источник отказал.';

export interface UseInboxResult {
  signals: InboundSignal[];
  sources: SignalSource[];
  loading: boolean;
  /** Источник, который читается прямо сейчас. */
  polling: number | null;
  error: string | null;
  /** Прочитать источник; лента перечитывается, если что-то приехало. */
  poll: (sourceId: number) => Promise<void>;
  reload: () => void;
}

/** Машинный код отказа из 409, если сервер его прислал. */
function refusalOf(error: unknown): string | null {
  if (!(error instanceof Error)) return null;
  const detail = (error as { detail?: unknown }).detail;
  if (detail !== null && typeof detail === 'object' && 'code' in detail) {
    return String((detail as { code: unknown }).code);
  }
  // `fetcher` кладёт тело отказа в сообщение, когда разобрать его не удалось.
  const known = Object.keys(REFUSAL_TEXT).find((code) => error.message.includes(code));
  return known ?? null;
}

function errorText(error: unknown): string {
  const code = refusalOf(error);
  if (code !== null) return REFUSAL_TEXT[code] ?? REFUSAL_FALLBACK;
  return error instanceof Error ? error.message : 'Unknown error';
}

/**
 * Входящие: лента и справочник источников.
 *
 * Прогон ручной и по одному источнику за раз: расписание живёт в воркере
 * (`#99`), а здесь человек нажимает и ждёт ответа. Два прогона одного источника
 * подряд боролись бы за его курсор, поэтому кнопка на время запроса заперта —
 * защёлкой, а не состоянием: два клика попадают в один рендер.
 */
export function useInbox(): UseInboxResult {
  const [signals, setSignals] = useState<InboundSignal[]>([]);
  const [sources, setSources] = useState<SignalSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [polling, setPolling] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const inFlight = useRef(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [feed, directory] = await Promise.all([
          inboxAPI.signals(),
          inboxAPI.sources(),
        ]);
        if (cancelled) return;
        setSignals(feed);
        setSources(directory);
        setError(null);
      } catch (failure) {
        if (!cancelled) setError(errorText(failure));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const poll = useCallback(async (sourceId: number) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setPolling(sourceId);
    setError(null);
    try {
      await inboxAPI.poll(sourceId);
      // Лента перечитывается целиком, а не склеивается: сервер знает, что
      // обновилось, а не только что приехало, и второй источник истины на
      // экране был бы догадкой.
      const [feed, directory] = await Promise.all([
        inboxAPI.signals(),
        inboxAPI.sources(),
      ]);
      setSignals(feed);
      setSources(directory);
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      inFlight.current = false;
      setPolling(null);
    }
  }, []);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);

  return { signals, sources, loading, polling, error, poll, reload };
}
