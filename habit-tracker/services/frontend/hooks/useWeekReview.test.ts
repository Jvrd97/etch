// [review:need-review] PHASE-03/221
// summary: tests for useWeekReview — the running week is asked for by a null code, the narrative of one week never lands on another, and a changed week starts from an idle narrative

import { afterEach, describe, expect, it } from 'bun:test';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import type { WeekNarrative, WeekReview } from '@/lib/api';
import { weekReviewFixture } from '@/components/week-review/test-fixture';
import { useWeekReview, type WeekReviewClient } from './useWeekReview';

afterEach(() => {
  cleanup();
});

function review(iso: string): WeekReview {
  const base = weekReviewFixture();
  return { ...base, window: { ...base.window, iso_code: iso } };
}

describe('useWeekReview', () => {
  it('asks for the running week with a null code and reads the code off the answer', async () => {
    const asked: Array<string | null> = [];
    const client: WeekReviewClient = {
      get: (iso) => {
        asked.push(iso);
        return Promise.resolve(review('2026-W36'));
      },
      narrative: () => Promise.reject(new Error('unused')),
    };

    const { result } = renderHook(() => useWeekReview(null, client));

    await waitFor(() => expect(result.current.state.status).toBe('ready'));
    expect(asked).toEqual([null]);
  });

  it('writes the narrative for the week on screen', async () => {
    const written: string[] = [];
    const client: WeekReviewClient = {
      get: (iso) => Promise.resolve(review(iso ?? '2026-W35')),
      narrative: (iso) => {
        written.push(iso);
        return Promise.resolve({ iso_code: iso, text: 'итог', model: 'm' });
      },
    };
    const { result } = renderHook(() => useWeekReview('2026-W35', client));
    await waitFor(() => expect(result.current.state.status).toBe('ready'));

    act(() => result.current.writeNarrative());

    await waitFor(() => expect(result.current.narrative).toEqual({ status: 'ready', text: 'итог' }));
    expect(written).toEqual(['2026-W35']);
  });

  it('drops a narrative that arrives after the reader moved to another week', async () => {
    let finish: (value: WeekNarrative) => void = () => undefined;
    const client: WeekReviewClient = {
      get: (iso) => Promise.resolve(review(iso ?? '2026-W35')),
      narrative: () => new Promise<WeekNarrative>((resolve) => (finish = resolve)),
    };
    const { result, rerender } = renderHook(({ iso }) => useWeekReview(iso, client), {
      initialProps: { iso: '2026-W35' as string | null },
    });
    await waitFor(() => expect(result.current.state.status).toBe('ready'));
    act(() => result.current.writeNarrative());
    expect(result.current.narrative.status).toBe('loading');

    rerender({ iso: '2026-W36' });
    await waitFor(() => {
      const { state } = result.current;
      expect(state.status === 'ready' && state.review.window.iso_code).toBe('2026-W36');
    });
    await act(async () => finish({ iso_code: '2026-W35', text: 'чужой итог', model: 'm' }));

    expect(result.current.narrative).toEqual({ status: 'idle' });
  });
});
