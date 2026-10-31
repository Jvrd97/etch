// [review:need-review] PHASE-03/244
// summary: tests for useHealthAdvice — idle until asked, the advice of the last seven days on success, «данных мало» on 422 apart from an error, its own words for 502/503 and for the dose net, and a second answer never written over a newer one

import { afterEach, describe, expect, it } from 'bun:test';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import type { HealthAdvice } from '@/lib/api';
import {
  ADVICE_ERROR_FALLBACK,
  DOSE_NET_TEXT,
  useHealthAdvice,
  type HealthAdviceClient,
} from './useHealthAdvice';

afterEach(() => {
  cleanup();
});

const ADVICE: HealthAdvice = {
  text: 'Ходи больше.\n\nЭто не медицинская рекомендация.',
  model: 'm',
  starts_on: '2026-10-24',
  ends_on: '2026-10-30',
  days: 7,
};

function clientFailing(error: unknown): HealthAdviceClient {
  return { write: () => Promise.reject(error) };
}

describe('useHealthAdvice', () => {
  it('asks nothing until it is asked', () => {
    let calls = 0;
    const { result } = renderHook(() =>
      useHealthAdvice({
        write: () => {
          calls += 1;
          return Promise.resolve(ADVICE);
        },
      })
    );

    expect(result.current.state).toEqual({ status: 'idle' });
    expect(calls).toBe(0);
  });

  it('keeps the advice with the days it was written for', async () => {
    const { result } = renderHook(() => useHealthAdvice({ write: () => Promise.resolve(ADVICE) }));

    act(() => result.current.write());

    await waitFor(() => expect(result.current.state).toEqual({ status: 'ready', advice: ADVICE }));
  });

  it('turns 422 into «not enough data», not into an error', async () => {
    const { result } = renderHook(() => useHealthAdvice(clientFailing({ status: 422 })));

    act(() => result.current.write());

    await waitFor(() => expect(result.current.state.status).toBe('not_enough_data'));
  });

  it('says in its own words that the model is off, did not answer, or was stopped by the dose net', async () => {
    const cases: Array<[unknown, string]> = [
      [{ status: 503 }, 'Совет от ИИ выключен'],
      [{ status: 502, message: 'Модель не ответила.' }, 'Модель не ответила'],
      [{ status: 502, message: 'Совет отклонён защитой.' }, DOSE_NET_TEXT],
      [new Error('boom'), ADVICE_ERROR_FALLBACK],
    ];
    for (const [error, expected] of cases) {
      const { result, unmount } = renderHook(() => useHealthAdvice(clientFailing(error)));

      act(() => result.current.write());

      await waitFor(() => expect(result.current.state.status).toBe('error'));
      const state = result.current.state;
      expect(state.status === 'error' && state.message).toContain(expected);
      unmount();
    }
  });

  it('drops the answer of an older ask when a newer one has been made', async () => {
    const resolvers: Array<(advice: HealthAdvice) => void> = [];
    const { result } = renderHook(() =>
      useHealthAdvice({
        write: () => new Promise<HealthAdvice>((resolve) => resolvers.push(resolve)),
      })
    );

    act(() => result.current.write());
    act(() => result.current.write());
    act(() => resolvers[1]({ ...ADVICE, text: 'новый' }));
    await waitFor(() => expect(result.current.state.status).toBe('ready'));
    act(() => resolvers[0]({ ...ADVICE, text: 'старый' }));

    const state = result.current.state;
    expect(state.status === 'ready' && state.advice.text).toBe('новый');
  });
});
