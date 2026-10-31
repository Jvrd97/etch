'use client';
// [review:need-review] PHASE-03/244
// summary: the advice for sleep, sport and supplements, written only when asked — four discriminated states (idle, loading, not enough data, error) plus the answer, 422 kept apart from a failure, and an answer of an older ask never written over a newer one

import { useCallback, useRef, useState } from 'react';
// A namespace import read at call time: other suites mock `@/lib/api` with a
// fixed list of names, and a named import of one they do not list would fail
// to link for every file that renders after them.
import * as api from '@/lib/api';
import type { HealthAdvice } from '@/lib/api';

/** The one call the block makes; a parameter so tests need no module mock. */
export interface HealthAdviceClient {
  write: () => Promise<HealthAdvice>;
}

const API_CLIENT: HealthAdviceClient = {
  write: () => api.healthAdviceAPI.write(),
};

export type HealthAdviceState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'not_enough_data' }
  | { status: 'error'; message: string }
  | { status: 'ready'; advice: HealthAdvice };

export const ADVICE_ERROR_FALLBACK = 'Не удалось написать совет.';
export const DOSE_NET_TEXT = 'Совет отклонён защитой: в нём была доза. Попробуйте ещё раз.';
const MODEL_OFF_TEXT = 'Совет от ИИ выключен: не настроен бэкенд модели.';
const MODEL_FAILED_TEXT = 'Модель не ответила. Повторите позже.';
const NOT_ENOUGH_DATA_STATUS = 422;
const BAD_GATEWAY = 502;
const SERVICE_UNAVAILABLE = 503;
// The server's own words for an answer the dose net dropped (`DOSE_GUARD_DETAIL`).
const DOSE_NET_MARK = 'защитой';

function statusOf(error: unknown): number | null {
  if (typeof error === 'object' && error !== null && 'status' in error) {
    const status = (error as { status: unknown }).status;
    if (typeof status === 'number') return status;
  }
  return null;
}

function messageOf(error: unknown): string {
  if (typeof error === 'object' && error !== null && 'message' in error) {
    const message = (error as { message: unknown }).message;
    if (typeof message === 'string') return message;
  }
  return '';
}

function failureState(error: unknown): HealthAdviceState {
  const status = statusOf(error);
  if (status === NOT_ENOUGH_DATA_STATUS) return { status: 'not_enough_data' };
  if (status === SERVICE_UNAVAILABLE) return { status: 'error', message: MODEL_OFF_TEXT };
  if (status === BAD_GATEWAY) {
    const dropped = messageOf(error).includes(DOSE_NET_MARK);
    return { status: 'error', message: dropped ? DOSE_NET_TEXT : MODEL_FAILED_TEXT };
  }
  return { status: 'error', message: ADVICE_ERROR_FALLBACK };
}

export interface UseHealthAdviceResult {
  state: HealthAdviceState;
  /** Ask the model for the advice; the server counts the last seven closed days itself. */
  write: () => void;
}

export function useHealthAdvice(client: HealthAdviceClient = API_CLIENT): UseHealthAdviceResult {
  const [state, setState] = useState<HealthAdviceState>({ status: 'idle' });
  // The number of the latest ask; an answer to an older one is dropped.
  const latest = useRef(0);

  const write = useCallback(() => {
    latest.current += 1;
    const ask = latest.current;
    setState({ status: 'loading' });
    client
      .write()
      .then((advice) => {
        if (latest.current === ask) setState({ status: 'ready', advice });
      })
      .catch((error: unknown) => {
        if (latest.current === ask) setState(failureState(error));
      });
  }, [client]);

  return { state, write };
}
