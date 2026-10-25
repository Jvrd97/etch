// [review:need-review] PHASE-03/200
// summary: tests for usePlanFacts — a write answers the card from its own response and re-reads the day, an answer lost on the way is retried under the key of the first attempt, a refusal is shown and frees the key, and a re-read day replaces what the hook holds

import { afterEach, describe, expect, it } from 'bun:test';
import { act, cleanup, renderHook } from '@testing-library/react';
import type { Category, PlanFactDraft, PlanFactWrite, PlanItemFacts } from '@/lib/api';
import { usePlanFacts, type PlanFactsClient } from './usePlanFacts';

afterEach(() => {
  cleanup();
});

const DATE = '2026-08-31';
const DRAFT: PlanFactDraft = { values: [{ field_id: 11, value: 300 }] };

function facts(total: number | null): PlanItemFacts {
  return {
    item_id: 'i1',
    link: {
      category_id: 1,
      category_name: 'Отжимания',
      category_active: true,
      field_id: 11,
      field_name: 'Повторения',
      field_type: 'number',
      unit: 'раз',
      target_value: 300,
      state: 'ok',
      fields: [],
    },
    entries: [],
    total,
    done: total !== null && total > 0,
    progress: total === null ? 'none' : 'met',
  };
}

function written(total: number): PlanFactWrite {
  return {
    entry_id: 7,
    facts: facts(total),
    mark: { item_id: 'i1', state: 'done', note: null, marked_at: null, updated_at: null, source: 'web' },
  };
}

/** A client that answers from a queue and remembers every key it was given. */
function client(answers: Array<PlanFactWrite | Error>): PlanFactsClient & { keys: string[] } {
  const keys: string[] = [];
  const next = async () => {
    const answer = answers.shift();
    if (answer === undefined) throw new Error('no answer queued');
    if (answer instanceof Error) throw answer;
    return answer;
  };
  return {
    keys,
    record: async (_date, _item, _draft, key) => {
      keys.push(key);
      return next();
    },
    correct: next,
    remove: next,
    categories: async (): Promise<Category[]> => [],
  };
}

describe('usePlanFacts', () => {
  it('draws the card from the answer and re-reads the day', async () => {
    const fake = client([written(300)]);
    let reloads = 0;
    const { result } = renderHook(() =>
      usePlanFacts(DATE, [facts(null)], () => {
        reloads += 1;
      }, fake)
    );

    await act(async () => {
      await result.current.record('i1', DRAFT);
    });

    expect(result.current.byItem.get('i1')?.total).toBe(300);
    expect(reloads).toBe(1);
  });

  it('retries a lost answer under the key of the first attempt', async () => {
    // A TypeError is what `fetch` throws when the connection drops: the server
    // may have written the fact, and only the same key keeps it from doubling.
    const fake = client([new TypeError('Failed to fetch'), written(300)]);
    const { result } = renderHook(() => usePlanFacts(DATE, [facts(null)], () => {}, fake));

    await act(async () => {
      await result.current.record('i1', DRAFT);
    });
    await act(async () => {
      await result.current.record('i1', DRAFT);
    });

    expect(fake.keys).toHaveLength(2);
    expect(fake.keys[0]).toBe(fake.keys[1]);
  });

  it('shows a refusal and gives the next attempt a new key', async () => {
    const refusal = Object.assign(new Error('An error occurred'), {
      status: 422,
      detail: { error: 'fact_invalid', reasons: ['поле 11 — число'] },
    });
    const fake = client([refusal, written(300)]);
    const { result } = renderHook(() => usePlanFacts(DATE, [facts(null)], () => {}, fake));

    await act(async () => {
      await result.current.record('i1', DRAFT);
    });
    expect(result.current.errors.get('i1')).toContain('поле 11 — число');

    await act(async () => {
      await result.current.record('i1', DRAFT);
    });
    expect(fake.keys[0]).not.toBe(fake.keys[1]);
    expect(result.current.errors.get('i1')).toBeUndefined();
  });

  it('takes a re-read day as the new truth', () => {
    const fake = client([]);
    const { result, rerender } = renderHook(
      ({ initial }) => usePlanFacts(DATE, initial, () => {}, fake),
      { initialProps: { initial: [facts(null)] } }
    );

    rerender({ initial: [facts(250)] });

    expect(result.current.byItem.get('i1')?.total).toBe(250);
  });
});
