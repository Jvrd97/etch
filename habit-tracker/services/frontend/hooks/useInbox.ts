'use client';
// [review:need-review] PHASE-03/97
// summary: inbox state — the feed of signals beside the directory of sources, the key of a source saved from the interface and never read back, one manual poll at a time with its refusal read as a machine code rather than as a sentence, and a re-read after anything that changed the server's answer

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  inboxAPI,
  type InboundSignal,
  type ProbeItem,
  type SignalSource,
} from '@/lib/api';

/** Что показывает экран, когда источник отказал. По машинному коду сервера. */
export const REFUSAL_TEXT: Record<string, string> = {
  source_disabled: 'Источник выключен — включите его, чтобы читать.',
  no_adapter: 'У источника нет адаптера: строка в справочнике есть, читать нечем.',
  no_credentials: 'Ключа нет — впишите его в карточке источника.',
  no_workspace: 'Не назван воркспейс: у ClickUp это числовой id рядом с ключом.',
  secret_unreadable:
    'Ключ не читается: сменился SESSION_SECRET. Введите ключ заново.',
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
  /** Сохранить ключ и настройки источника. Ключ обратно не приходит. */
  saveCredentials: (
    sourceId: number,
    secret: string | null,
    settings: Record<string, string>
  ) => Promise<void>;
  /** Включить или выключить источник. */
  toggle: (sourceId: number, active: boolean) => Promise<void>;
  /** Спросить источник, что он видит, ничего не записывая. */
  probe: (sourceId: number) => Promise<void>;
  /** Чем кончилась последняя проба каждого источника. */
  probes: Record<number, ProbeState>;
  reload: () => void;
}

/**
 * Чем кончилась проба одного источника.
 *
 * Размеченное объединение, а не пара «список плюс ошибка»: «ещё не пробовали»,
 * «пусто» и «отказ» — три разных состояния, и на экране они выглядят
 * по-разному. Пара полей позволила бы выразить четвёртое, которого не бывает.
 */
export type ProbeState =
  | { status: 'ok'; count: number; items: ProbeItem[] }
  | { status: 'failed'; message: string };

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
  const [probes, setProbes] = useState<Record<number, ProbeState>>({});
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

  const probe = useCallback(async (sourceId: number) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setPolling(sourceId);
    try {
      const outcome = await inboxAPI.probe(sourceId);
      setProbes((current) => ({
        ...current,
        [sourceId]: { status: 'ok', count: outcome.count, items: outcome.items },
      }));
    } catch (failure) {
      // Отказ пробы живёт на карточке источника, а не в общей полосе ошибки
      // экрана: он про этот источник, и рядом с ним его и читают.
      setProbes((current) => ({
        ...current,
        [sourceId]: { status: 'failed', message: errorText(failure) },
      }));
    } finally {
      inFlight.current = false;
      setPolling(null);
    }
  }, []);

  const saveCredentials = useCallback(
    async (
      sourceId: number,
      secret: string | null,
      settings: Record<string, string>
    ) => {
      setError(null);
      try {
        const saved = await inboxAPI.setCredentials(sourceId, { secret, settings });
        // Ответ сервера — истина: он и говорит, задан ли теперь ключ.
        setSources((current) =>
          current.map((one) => (one.id === saved.id ? saved : one))
        );
      } catch (failure) {
        setError(errorText(failure));
      }
    },
    []
  );

  const toggle = useCallback(async (sourceId: number, active: boolean) => {
    setError(null);
    try {
      const saved = await inboxAPI.patchSource(sourceId, { is_active: active });
      setSources((current) =>
        current.map((one) => (one.id === saved.id ? saved : one))
      );
    } catch (failure) {
      setError(errorText(failure));
    }
  }, []);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);

  return {
    signals,
    sources,
    loading,
    polling,
    error,
    poll,
    saveCredentials,
    toggle,
    probe,
    probes,
    reload,
  };
}
