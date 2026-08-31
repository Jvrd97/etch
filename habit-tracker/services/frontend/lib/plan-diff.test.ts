// [review:need-review] PHASE-03/150
// summary: tests of the diff read into Russian — the caption naming the window the machine proposed, the first recorded value rather than the last, the summary above the plan, and the two different silences («не генерировали» and «ничего не меняли»)

import { describe, expect, it } from 'bun:test';
import type { PlanDiff, PlanItemDiff } from '@/lib/api';
import { diffSummary, proposalLine, proposalsOf } from './plan-diff';

function change(field: string, oldValue: string | null, newValue: string | null) {
  return {
    field: field as PlanItemDiff['changes'][number]['field'],
    old_value: oldValue,
    new_value: newValue,
    author: 'human' as const,
    revision_from: 0,
    changed_at: '2026-08-30T09:00:00+00:00',
  };
}

function item(...changes: PlanItemDiff['changes']): PlanItemDiff {
  return { plan_item_id: 'i1', text_md: 'Задача W1', changes };
}

function diff(overrides: Partial<PlanDiff> = {}): PlanDiff {
  return {
    day_date: '2026-08-30',
    revision_zero: 0,
    revision_zero_author: 'ai',
    latest_revision: 1,
    moved_items: 1,
    items: [item(change('window_start', '09:00', '14:00'), change('window_end', '11:00', '15:00'))],
    ...overrides,
  };
}

describe('proposalLine', () => {
  it('names the window the machine proposed, glued back together', () => {
    const line = proposalLine(
      item(change('window_start', '09:00', '14:00'), change('window_end', '11:00', '15:00')),
      'ai'
    );

    expect(line).toBe('AI предлагал 09:00-11:00');
  });

  it('takes the first recorded value, not the last', () => {
    // Человек мог поправить окно трижды; интересно то, с чего он начал, —
    // предложение, а не предпоследняя его же попытка.
    const line = proposalLine(
      item(
        change('window_start', '09:00', '10:00'),
        change('window_start', '10:00', '14:00')
      ),
      'ai'
    );

    expect(line).toBe('AI предлагал 09:00-…');
  });

  it('says of a line the person added that nobody proposed it', () => {
    const line = proposalLine(item(change('status', null, 'added')), 'fallback');

    expect(line).toBe('скелет этого пункта не предлагал');
  });

  it('says where the machine put a line the person moved', () => {
    const line = proposalLine(item(change('ord', '0', '2')), 'ai');

    expect(line).toBe('AI ставил его на другое место');
  });
});

describe('proposalsOf', () => {
  it('keys the captions by item so the plan can print them where they belong', () => {
    expect(proposalsOf(diff()).get('i1')).toBe('AI предлагал 09:00-11:00');
  });

  it('has nothing to say about a day with no diff', () => {
    expect(proposalsOf(null).size).toBe(0);
  });
});

describe('diffSummary', () => {
  it('counts the moved items the way Russian counts', () => {
    expect(diffSummary(diff({ moved_items: 1 }))).toBe(
      'Человек переставил 1 пункт из того, что предложил AI'
    );
    expect(diffSummary(diff({ moved_items: 3 }))).toBe(
      'Человек переставил 3 пункта из того, что предложил AI'
    );
  });

  it('is silent when nobody generated a plan — there is nothing to compare with', () => {
    expect(diffSummary(diff({ revision_zero: null }))).toBeNull();
  });

  it('is silent when the person changed nothing — the comparison agreed', () => {
    expect(diffSummary(diff({ moved_items: 0 }))).toBeNull();
  });
});
